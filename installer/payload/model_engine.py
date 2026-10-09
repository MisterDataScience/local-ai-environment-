"""Single serial owner of model loading, backend work and memory handoffs."""

import concurrent.futures
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.parse import urlparse
import uuid

from backend_http import api, port_open
from routing import messages_and_route
from text_models import configured_text_models, output_ceiling
from context_policy import compaction_policy
from web_client import retrieve
from tool_protocol import tools_for_ollama, assistant_for_openai
from workflows import fill_workflow, output_files
import resource_modes
import reverse_image
import vault_media
import speech
import token_stream
from conversation_audio import Audio
from vault_tools import mounted_root, enabled as vault_enabled

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("gateway")


def output_limit(body, mode="max", preset=None):
    ceiling = output_ceiling(mode, preset)
    requested = []
    for key in ("max_tokens", "max_completion_tokens"):
        if key in body:
            value = body[key]
            if type(value) is not int or value <= 0:
                raise ValueError(f"{key} must be a positive integer")
            requested.append(value)
    return min([ceiling, *requested])


class Engine:
    def __init__(self, config, root=ROOT):
        self.config, self.root = config, root
        if config.get("github", {}).get("enabled"):
            raise ValueError("GitHub activation is not available until credential and approval integration is validated")
        self.text_models = configured_text_models(config)
        self.ollama = config.get("ollama_url", "http://127.0.0.1:11434")
        self.comfy = config.get("comfy_url", "http://127.0.0.1:8188")
        self.comfy_port = urlparse(self.comfy).port
        self.process = None
        self.log_file = None
        self.state = "idle"
        self.text_profile = None
        (root / "media").mkdir(exist_ok=True)
        (root / "logs").mkdir(exist_ok=True)
        # A single executor owns every model operation, including waiting for unloads.
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.pending = threading.BoundedSemaphore(4)
        self.mode_lock = threading.RLock()
        self.mode = resource_modes.load(root)
        self.mode_epoch = 0
        self.instance_id = uuid.uuid4().hex
        self.mode_transitioning = False
        self.mode_error = None
        self.audio = Audio(self)

    def mode_status(self):
        with self.mode_lock:
            return {'mode': self.mode, 'transitioning': self.mode_transitioning,
                    'error': self.mode_error, 'description': resource_modes.MODES[self.mode],
                    'epoch': self.mode_epoch, 'instance_id': self.instance_id}

    def visible_models(self):
        with self.mode_lock:
            return {key: preset for key, preset in self.text_models.items()
                    if resource_modes.allowed(self.mode, key, preset)}

    def context_status(self):
        with self.mode_lock:
            return compaction_policy(self.text_models, self.mode)

    def check_policy(self, body, route):
        with self.mode_lock:
            if self.mode_transitioning or self.mode_error:
                raise RuntimeError('Mode switch is not ready. Check AI Modes before submitting another request.')
            if not resource_modes.allowed(self.mode, body['model'], self.text_models[body['model']], route):
                raise ValueError('Blocked by ' + self.mode + ' mode. Select an eligible model or change AI Modes on the Mac.')

    def change_mode(self, mode):
        if mode not in resource_modes.MODES:
            raise ValueError('Choose gaming, normal or max.')
        with self.mode_lock:
            if self.mode_transitioning:
                raise RuntimeError('A mode switch is already in progress.')
            if not any(resource_modes.allowed(mode, key, preset) for key, preset in self.text_models.items()):
                raise ValueError('This mode needs its supported local text preset installed. Rerun the installer.')
            resource_modes.save(self.root, mode)
            self.mode, self.mode_transitioning, self.mode_error = mode, True, None
            self.mode_epoch += 1
            # The serial barrier runs after the active job. Queued old jobs are
            # invalidated immediately and never begin another model operation.
            self.executor.submit(self.finish_mode_change)
        return self.mode_status()

    def finish_mode_change(self):
        self.audio.control('stop')
        try:
            self.stop_comfy()
            if port_open(self.comfy_port):
                raise RuntimeError('Unmanaged ComfyUI is still running.')
            self.unload_ollama()
        except Exception:
            with self.mode_lock:
                self.mode_error = 'Model release failed. Stop Local AI and check the backend before retrying.'
        finally:
            with self.mode_lock:
                self.mode_transitioning = False
                self.state = 'idle'

    def submit(self, body, stream=None):
        # Internal callbacks can only originate in the HTTP handler.
        body.pop('_stream', None)
        if stream is not None:
            body['_stream'] = stream
        body.pop("_usage", None)
        body.pop("_finish_reason", None)
        output_limit(body)  # Validate before admitting work or loading models.
        messages, route, prompt = messages_and_route(body, self.text_models)
        if any(m.get("images") for m in messages):
            model = self.text_models[body["model"]]["model"].lower()
            if not ("qwen3.5" in model or "gemma4" in model):
                raise ValueError("Selected model does not have verified vision support; select Qwen3.5.")
            if route != "text":
                raise ValueError("Image input is supported only for text questions.")
            if self.mode == 'gaming':
                raise ValueError("Visual inference requires Normal or Max mode.")
        if route == 'speak':
            body['_speech_request'] = speech.request(self.config, self.root, prompt, body.get('speech'))
        elif 'speech' in body:
            raise ValueError('Speech options require the /speak route.')
        with self.mode_lock:
            self.check_policy(body, route)
            if 'media_mode_token' in body:
                expected = f'{self.instance_id}:{self.mode_epoch}:{self.mode}'
                if route not in {'image', 'video', 'speak'} or body['media_mode_token'] != expected:
                    raise ValueError('Media work-agent mode changed. Restart the work agent.')
            epoch = self.mode_epoch
            if not self.pending.acquire(blocking=False):
                raise RuntimeError('Four requests are already queued. Wait for them to finish.')
            try:
                future = self.executor.submit(self.run_admitted, epoch, messages, route, prompt, body)
            except Exception:
                self.pending.release()
                raise
            future.add_done_callback(lambda _: self.pending.release())
            return future

    def run_admitted(self, epoch, messages, route, prompt, body):
        with self.mode_lock:
            if epoch != self.mode_epoch:
                raise RuntimeError('Request cancelled because the resource mode changed. Submit it again.')
            self.check_policy(body, route)
        return self.run(messages, route, prompt, body)

    def unload_ollama(self):
        self.state = "unloading-text"
        self.text_profile = None
        loaded = api(self.ollama, "/api/ps").get("models", [])
        for model in loaded:
            api(self.ollama, "/api/generate", {"model": model["name"], "keep_alive": 0}, timeout=120)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if not api(self.ollama, "/api/ps").get("models"):
                return
            time.sleep(0.5)
        raise RuntimeError("Ollama did not confirm unload. ComfyUI was not started.")

    def start_comfy(self):
        if port_open(self.comfy_port):
            raise RuntimeError("ComfyUI port is occupied. Stop your manually started ComfyUI first.")
        directory = Path(self.config["comfy_dir"]).expanduser()
        python = directory / ".venv/bin/python"
        if not python.is_file() or not (directory / "main.py").is_file():
            raise RuntimeError(f"ComfyUI installation is incomplete: {directory}")
        # Vault-mode ComfyUI diagnostics can contain the submitted prompt. Keep
        # them out of plaintext logs; the gateway reports bounded generic errors.
        self.log_file = open(os.devnull, 'ab') if vault_enabled(self.config) else (self.root / "logs/comfy.log").open("ab")
        self.state = "starting-comfy"
        env = os.environ.copy()
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        command = [str(python), "main.py", "--listen", "127.0.0.1", "--port", str(self.comfy_port),
                   "--disable-auto-launch", "--disable-api-nodes", "--disable-all-custom-nodes"]
        if vault_enabled(self.config):
            with mounted_root(self.config):
                pass
            import imageio_ffmpeg
            env.update(LOCAL_AI_CONTROL=str(self.root), LOCAL_AI_VAULT=json.dumps(self.config['vault']),
                       LOCAL_AI_FFMPEG=imageio_ffmpeg.get_ffmpeg_exe())
            command += ['--whitelist-custom-nodes', 'local_ai_vault',
                        '--disable-metadata', '--preview-method', 'none']
        self.process = subprocess.Popen(
            command,
            cwd=directory, stdout=self.log_file, stderr=subprocess.STDOUT,
            env=env, start_new_session=True,
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("ComfyUI exited during startup. Read logs/comfy.log.")
            try:
                api(self.comfy, "/system_stats", timeout=2)
                return
            except (URLError, TimeoutError, OSError):
                time.sleep(1)
        raise RuntimeError("ComfyUI startup exceeded three minutes. Read logs/comfy.log.")

    def stop_comfy(self):
        process = self.process
        if process is None:
            return
        self.state = "releasing-comfy"
        try:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
            if port_open(self.comfy_port):
                raise RuntimeError("ComfyUI port remains occupied; model handoff stopped.")
        finally:
            # Keep the handle if cleanup failed, so the next request must retry it.
            if process.poll() is not None and not port_open(self.comfy_port):
                self.process = None
                if self.log_file:
                    self.log_file.close()
                    self.log_file = None

    def render(self, kind, prompt):
        with self.mode_lock:
            if self.mode_transitioning or self.mode_error or self.mode == 'gaming' or (self.mode == 'normal' and kind == 'video'):
                raise RuntimeError('Media generation blocked by resource mode.')
            render_epoch = self.mode_epoch
        encrypted = vault_enabled(self.config)
        if encrypted:
            with mounted_root(self.config):
                pass
        template = json.loads((self.root / "workflows" / f"{kind}.json").read_text())
        workflow = fill_workflow(template, prompt)
        if encrypted:
            workflow = vault_media.encrypted_workflow(workflow, kind)
        self.unload_ollama()
        try:
            self.start_comfy()
            submitted = api(self.comfy, "/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
            prompt_id = submitted["prompt_id"]
            self.state = f"rendering-{kind}"
            deadline = time.monotonic() + self.config.get("render_timeout_seconds", 3600)
            while time.monotonic() < deadline:
                if render_epoch != self.mode_epoch:
                    raise RuntimeError('Render cancelled because the resource mode changed.')
                if encrypted:
                    with mounted_root(self.config):
                        pass
                if self.process.poll() is not None:
                    raise RuntimeError("ComfyUI exited during rendering. Read logs/comfy.log.")
                history = api(self.comfy, f"/history/{prompt_id}").get(prompt_id)
                if history:
                    status = history.get("status", {})
                    if status.get("status_str") == "error":
                        detail = 'Encrypted render failed; check the vault is unlocked.' if encrypted else json.dumps(status.get('messages', []))[:4000]
                        raise RuntimeError("ComfyUI render failed: " + detail)
                    if status.get("completed"):
                        files = list(output_files(history))
                        if not files:
                            raise RuntimeError("Workflow finished without a saved output file.")
                        item = files[0]
                        suffix = Path(item["filename"]).suffix.lower()
                        if suffix not in {".png", ".webp", ".mp4", ".webm"}:
                            raise RuntimeError("Unsupported generated file extension.")
                        if encrypted:
                            if suffix != ('.png' if kind == 'image' else '.mp4') or item.get('subfolder') != 'Media':
                                raise RuntimeError('Unexpected encrypted media result.')
                            with vault_media.open_media(self.config, item['filename']) as (saved, size, root_fd):
                                if size <= 0:
                                    raise RuntimeError('Generated media is empty.')
                            destination = Path(item['filename'])
                            break
                        output_dir = (Path(self.config["comfy_dir"]).expanduser() / "output").resolve()
                        source = (output_dir / item.get("subfolder", "") / item["filename"]).resolve()
                        if not source.is_relative_to(output_dir):
                            raise RuntimeError("Output path escaped the ComfyUI output folder.")
                        destination = self.root / "media" / (uuid.uuid4().hex + suffix)
                        shutil.copyfile(source, destination)
                        break
                time.sleep(1)
            else:
                raise RuntimeError("Rendering timed out. ComfyUI will now be stopped.")
        finally:
            # Process teardown releases the MPS allocator as well as model weights.
            self.stop_comfy()
        if kind == "video" and destination.suffix == ".webp":
            destination = self.convert_video(destination)
        remote = self.config.get("remote_access", {})
        base = remote["media_url"] if remote.get("enabled") else self.config.get("public_url", "http://127.0.0.1:8000")
        url = base + "/media/" + destination.name
        if kind == "image":
            return f"![Generated image]({url})\n\n[Download image]({url})"
        return f"[Open or download generated video]({url})"

    def convert_video(self, source):
        from PIL import Image, ImageSequence
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if not ffmpeg:
            raise RuntimeError("Install ffmpeg with Homebrew. The WebP output is preserved in media/.")
        destination = source.with_suffix(".mp4")
        with tempfile.TemporaryDirectory() as directory:
            with Image.open(source) as image:
                for index, frame in enumerate(ImageSequence.Iterator(image)):
                    frame.convert("RGB").save(Path(directory) / f"{index:05d}.png")
            result = subprocess.run(
                [ffmpeg, "-v", "error", "-y", "-framerate", "12", "-i",
                 str(Path(directory) / "%05d.png"), "-c:v", "libx264", "-pix_fmt",
                 "yuv420p", "-movflags", "+faststart", str(destination)],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode:
                raise RuntimeError("Video conversion failed: " + result.stderr[-2000:])
        return destination

    def run(self, messages, route, prompt, body):
        from model_team import team_roles
        roles = team_roles(self.config, self.text_models)
        light = (route == 'text' and roles and body['model'] == roles['coordinator']
                 and self.text_models[body['model']]['num_ctx'] <= 8192)
        with self.audio.model_job(light=bool(light)):
            try:
                return self.run_inner(messages, route, prompt, body)
            finally:
                if not light and self.audio.enabled:
                    # Audio may reload only after the large model is gone.
                    self.unload_ollama()

    def start_conversation(self):
        def start():
            with self.audio.model_job():
                self.stop_comfy()
                if port_open(self.comfy_port):
                    raise RuntimeError('Stop unmanaged ComfyUI before conversation')
                self.unload_ollama()
                return self.audio.control('start')
        return self.executor.submit(start).result(timeout=180)

    def run_inner(self, messages, route, prompt, body):
        LOG.info("Starting %s request", route)
        try:
            self.check_policy(body, route)
            self.stop_comfy()
            if port_open(self.comfy_port):
                raise RuntimeError("Stop manually started ComfyUI. The gateway must own it.")
            if route in {"image", "video"}:
                return self.render(route, prompt)
            if route == 'speak':
                self.unload_ollama()
                self.state = 'generating-speech'
                return speech.generate(self.config, self.root, body['_speech_request'])
            if route == "reverse":
                self.state = "retrieving-reverse-image"
                return reverse_image.format_result(reverse_image.search_tool(self.config, prompt))
            links = ""
            preset = dict(self.text_models[body['model']])
            if self.mode == 'gaming':
                preset.update(num_ctx=min(preset['num_ctx'], 4096),
                              keep_alive_seconds=min(preset['keep_alive_seconds'], 120), thinking=False)
            if route in {"search", "read"}:
                self.state = "retrieving-web"
                budget = max(500, min(10000, (preset["num_ctx"] - 2600) * 2))
                messages, links = retrieve(self.config, route, prompt, budget)
            # Switching text models also explicitly releases the old model.
            loaded = api(self.ollama, "/api/ps").get("models", [])
            profile = (preset['model'], preset['num_ctx'], preset.get('thinking', False))
            if loaded and (any(model["name"] != preset["model"] for model in loaded)
                           or self.text_profile != profile):
                self.unload_ollama()
            self.check_policy(body, route)
            self.state = "generating-text"
            if any(m.get('images') for m in messages):
                capabilities = api(self.ollama, '/api/show', {'model': preset['model']}).get('capabilities', [])
                if 'vision' not in capabilities:
                    raise ValueError('The installed model has no vision capability. Use an installed Qwen3.5 vision artifact.')
            options = {"num_ctx": preset["num_ctx"], "num_predict": output_limit(body, self.mode, preset)}
            if isinstance(body.get("temperature"), (int, float)):
                options["temperature"] = body["temperature"]
            payload = {
                "model": preset["model"], "messages": messages,
                "options": options, "stream": False,
                # Preserve the full rendered input, including tools. Oversized
                # requests must fail rather than silently discard instructions.
                "truncate": False, "shift": False,
                "think": preset.get("thinking", False), "keep_alive": preset["keep_alive_seconds"],
            }
            tools = tools_for_ollama(body) if route == "text" else []
            if tools:
                payload["tools"] = tools
            # Exactly one inference call. Open WebUI executes/approves tools and
            # submits the next inference turn with their results.
            stream = body.get('_stream') if route == 'text' else None
            response = (token_stream.chat(self.ollama, payload, stream) if stream
                        else api(self.ollama, '/api/chat', payload, timeout=1800))
            self.text_profile = profile
            message = response['message']
            counts = [response.get('prompt_eval_count'), response.get('eval_count')]
            if all(type(n) is int and n >= 0 for n in counts):
                body['_usage'] = {'prompt_tokens': counts[0], 'completion_tokens': counts[1],
                                  'total_tokens': sum(counts)}
            answer = assistant_for_openai(message, tools)
            if stream:
                if isinstance(answer, dict) and answer.get('tool_calls'):
                    delta = {'tool_calls': [dict(call, index=i) for i, call in enumerate(answer['tool_calls'])]}
                    if answer.get('reasoning_content'):
                        delta['reasoning_content'] = answer['reasoning_content']
                    stream.send(delta)
                body['_streamed'] = True
            # Preserve the backend's cutoff signal instead of calling every
            # non-tool response a normal stop. Counts alone cannot prove cutoff.
            body['_finish_reason'] = ('length' if response.get('done_reason') == 'length'
                                      else 'tool_calls' if isinstance(answer, dict) and answer.get('tool_calls')
                                      else 'stop')
            return answer + links if isinstance(answer, str) else answer
        finally:
            self.state = "idle"
            LOG.info("Finished %s request", route)


