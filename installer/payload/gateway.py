"""Single-user, loopback-only chat gateway with serial model handoffs."""

import concurrent.futures
import copy
import fcntl
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid
from text_models import configured_text_models

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("gateway")
MODEL_ID = "local-ai"


def api(base, path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read(8192).decode(errors="replace")
        raise RuntimeError(f"Backend rejected {path}: HTTP {error.code}: {detail}") from error


def port_open(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def messages_and_route(body, model_ids=None):
    if not isinstance(body, dict):
        raise ValueError("The request body must be a JSON object.")
    if body.get("model") not in (model_ids if model_ids is not None else {MODEL_ID}):
        raise ValueError("Choose one of the configured local-ai text presets in Open WebUI.")
    if body.get("tools"):
        raise ValueError("This starter gateway does not implement tool calling.")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list.")
    cleaned = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each message must be an object.")
        role, content = message.get("role"), message.get("content")
        if role not in {"system", "user", "assistant", "developer"}:
            raise ValueError("Only ordinary text chat messages are supported.")
        if not isinstance(content, str):
            raise ValueError("Use text prompts. Image/audio attachments are not implemented.")
        cleaned.append({"role": "system" if role == "developer" else role, "content": content})
    latest = next((m["content"] for m in reversed(cleaned) if m["role"] == "user"), "")
    stripped = latest.strip()
    # Whitespace after a command may also be a newline or a tab.
    parts = stripped.split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    if command in {"/image", "/video"}:
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("Put a description after /image or /video.")
        return cleaned, command[1:], parts[1].strip()
    return cleaned, "text", latest


def fill_workflow(template, prompt):
    workflow = copy.deepcopy(template)
    found = False
    seed = secrets.randbelow(2**31)
    for node in workflow.values():
        for key, value in node.get("inputs", {}).items():
            if isinstance(value, str) and "__LOCAL_AI_PROMPT__" in value:
                node["inputs"][key] = value.replace("__LOCAL_AI_PROMPT__", prompt)
                found = True
            if key in {"seed", "noise_seed"} and isinstance(value, int):
                node["inputs"][key] = seed
    if not found:
        raise ValueError("Workflow has no __LOCAL_AI_PROMPT__ marker.")
    return workflow


def output_files(history):
    for output in history.get("outputs", {}).values():
        for values in output.values():
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict) and item.get("filename") and item.get("type") == "output":
                        yield item


class Engine:
    def __init__(self, config, root=ROOT):
        self.config, self.root = config, root
        self.text_models = configured_text_models(config)
        self.ollama = config.get("ollama_url", "http://127.0.0.1:11434")
        self.comfy = config.get("comfy_url", "http://127.0.0.1:8188")
        self.comfy_port = urlparse(self.comfy).port
        self.process = None
        self.log_file = None
        self.state = "idle"
        (root / "media").mkdir(exist_ok=True)
        (root / "logs").mkdir(exist_ok=True)
        # A single executor owns every model operation, including waiting for unloads.
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.pending = threading.BoundedSemaphore(4)

    def submit(self, body):
        messages, route, prompt = messages_and_route(body, self.text_models)
        if not self.pending.acquire(blocking=False):
            raise RuntimeError("Four requests are already queued. Wait for them to finish.")
        future = self.executor.submit(self.run, messages, route, prompt, body)
        future.add_done_callback(lambda _: self.pending.release())
        return future

    def unload_ollama(self):
        self.state = "unloading-text"
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
        self.log_file = (self.root / "logs/comfy.log").open("ab")
        self.state = "starting-comfy"
        env = os.environ.copy()
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        self.process = subprocess.Popen(
            [str(python), "main.py", "--listen", "127.0.0.1", "--port", str(self.comfy_port),
             "--disable-auto-launch", "--disable-api-nodes"],
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
        template = json.loads((self.root / "workflows" / f"{kind}.json").read_text())
        workflow = fill_workflow(template, prompt)
        self.unload_ollama()
        try:
            self.start_comfy()
            submitted = api(self.comfy, "/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
            prompt_id = submitted["prompt_id"]
            self.state = f"rendering-{kind}"
            deadline = time.monotonic() + self.config.get("render_timeout_seconds", 3600)
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("ComfyUI exited during rendering. Read logs/comfy.log.")
                history = api(self.comfy, f"/history/{prompt_id}").get(prompt_id)
                if history:
                    status = history.get("status", {})
                    if status.get("status_str") == "error":
                        raise RuntimeError("ComfyUI render failed: " + json.dumps(status.get("messages", []))[:4000])
                    if status.get("completed"):
                        files = list(output_files(history))
                        if not files:
                            raise RuntimeError("Workflow finished without a saved output file.")
                        item = files[0]
                        suffix = Path(item["filename"]).suffix.lower()
                        if suffix not in {".png", ".webp", ".mp4", ".webm"}:
                            raise RuntimeError("Unsupported generated file extension.")
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
        url = self.config.get("public_url", "http://127.0.0.1:8000") + "/media/" + destination.name
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
        LOG.info("Starting %s request", route)
        try:
            self.stop_comfy()
            if port_open(self.comfy_port):
                raise RuntimeError("Stop manually started ComfyUI. The gateway must own it.")
            if route != "text":
                return self.render(route, prompt)
            preset = self.text_models[body["model"]]
            # Switching text models also explicitly releases the old model.
            loaded = api(self.ollama, "/api/ps").get("models", [])
            if any(model["name"] != preset["model"] for model in loaded):
                self.unload_ollama()
            self.state = "generating-text"
            options = {"num_ctx": preset["num_ctx"], "num_predict": 2048}
            if isinstance(body.get("temperature"), (int, float)):
                options["temperature"] = body["temperature"]
            result = api(self.ollama, "/api/chat", {
                "model": preset["model"], "messages": messages,
                "options": options, "stream": False,
                "think": preset.get("thinking", False), "keep_alive": preset["keep_alive_seconds"],
            }, timeout=1800)
            return result["message"]["content"]
        finally:
            self.state = "idle"
            LOG.info("Finished %s request", route)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, message, *args):
        LOG.info(message, *args)

    def json_response(self, code, value):
        content = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def authorised(self):
        expected = "Bearer " + self.server.engine.config["api_key"]
        if not secrets.compare_digest(self.headers.get("Authorization", ""), expected):
            self.json_response(401, {"error": {"message": "Gateway API key is missing or incorrect."}})
            return False
        return True

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self.json_response(200, {"status": "ok", "state": self.server.engine.state})
        if path.startswith("/media/"):
            # Files have unguessable generated names; service is bound only to loopback.
            name = path.removeprefix("/media/")
            if "/" in name or "\\" in name or ".." in name:
                return self.json_response(404, {"error": "Not found"})
            file = self.server.engine.root / "media" / name
            if not file.is_file():
                return self.json_response(404, {"error": "Not found"})
            types = {".png": "image/png", ".webp": "image/webp", ".mp4": "video/mp4", ".webm": "video/webm"}
            self.send_response(200)
            self.send_header("Content-Type", types.get(file.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(file.stat().st_size))
            self.send_header("Cache-Control", "private, max-age=3600")
            self.end_headers()
            with file.open("rb") as content:
                shutil.copyfileobj(content, self.wfile)
            return
        if not self.authorised():
            return
        if path == "/v1/models":
            return self.json_response(200, {"object": "list", "data": [
                {"id": identifier, "name": preset["name"], "object": "model", "created": 0,
                 "owned_by": "local"} for identifier, preset in self.server.engine.text_models.items()]})
        self.json_response(404, {"error": "Not found"})

    def do_POST(self):
        if not self.authorised():
            return
        if urlparse(self.path).path != "/v1/chat/completions":
            return self.json_response(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("Request must be between 1 byte and 2 MB.")
            body = json.loads(self.rfile.read(length))
            future = self.server.engine.submit(body)
        except (ValueError, RuntimeError) as error:
            return self.json_response(400, {"error": {"message": str(error)}})
        identifier, created = "chatcmpl-" + uuid.uuid4().hex, int(time.time())
        if not body.get("stream"):
            try:
                content = future.result()
                return self.json_response(200, {"id": identifier, "object": "chat.completion",
                    "created": created, "model": body["model"], "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]})
            except Exception as error:
                LOG.exception("Request failed")
                return self.json_response(502, {"error": {"message": str(error)}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            while not future.done():
                try:
                    future.result(timeout=10)
                except concurrent.futures.TimeoutError:
                    self.wfile.write(b": waiting for local model\n\n")
                    self.wfile.flush()
                except Exception:
                    break
            try:
                content = future.result()
            except Exception as error:
                LOG.exception("Request failed")
                content = "Local generation failed: " + str(error)
            for delta, finish in [({"role": "assistant", "content": content}, None), ({}, "stop")]:
                chunk = {"id": identifier, "object": "chat.completion.chunk", "created": created,
                         "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # The job still owns the executor until cleanup, even if the tab closes.
            LOG.info("Client disconnected; job will finish and release model memory.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock_file = (ROOT / ".gateway.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another copy of this gateway is already running.")
    config = json.loads((ROOT / "config.json").read_text())
    if port_open(urlparse(config.get("comfy_url", "http://127.0.0.1:8188")).port):
        raise SystemExit("Stop manually started ComfyUI before starting the gateway.")
    server = ThreadingHTTPServer(("127.0.0.1", config.get("gateway_port", 8000)), Handler)
    server.daemon_threads = True
    server.engine = Engine(config)
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        LOG.info("Gateway listening at %s", config.get("public_url", "http://127.0.0.1:8000"))
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Waiting for queued work before shutdown; do not force-close this window.")
    finally:
        server.server_close()
        server.engine.executor.shutdown(wait=True)
        server.engine.stop_comfy()
        lock_file.close()


if __name__ == "__main__":
    main()
