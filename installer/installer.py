"""Resumable installer for the chosen single-user Apple Silicon stack."""
import argparse
import datetime
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from urllib.error import HTTPError

from common import PORTS, http, launch, ollama_binary, ollama_environment, port_open, stop_process, wait_ready, webui_environment

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE / "payload"))
from text_models import configured_text_models, upgrade_text_configuration
from model_team import upgrade_team
from context_policy import require_backend_version
from context_settings import ContextSettings
COMFY_RELEASE = "v0.38.0"
WEBUI_RELEASE = "0.11.1"
OLLAMA_CONTEXT_RELEASE = '0.40.0'
OLLAMA_CONTEXT_SHA256 = '60dd339e77fdc8afe3286c51ff1fd8eb4f467ec178f33f4a85ec69dac6f2b9dd'
GATEWAY_FILES = ("gateway.py", "backend_http.py", "routing.py", "workflows.py",
                 "model_engine.py", "http_api.py", "text_models.py", "web_client.py",
                 "tool_protocol.py", "image_inputs.py", "web_tools_api.py", "reverse_image.py", "vault_tools.py", "vault_media.py", "resource_modes.py", "context_policy.py", "model_team.py", "speech.py", "speech_worker.py")
GATEWAY_FILES += ('token_stream.py', 'conversation_audio.py', 'conversation_worker.py')
GATEWAY_FILES += ('capability_discovery.py',)
GATEWAY_FILES += ('inference_scheduler.py', 'captain_config.py', 'shared_llama.py')
TEAM_FILES = ('work_agent.py', 'opencode-team.mjs', 'handoff-contract.mjs', 'team_setup.py', 'voice_setup.py',
              'office_setup.py', 'office_mcp.py', 'office_check.py', 'browser_agent.py', 'browser_setup.py',
               'tool_availability.py', 'pdf_reader.py', 'pdf_mcp.py', 'transfer_mcp.py', 'file_transfer.py', 'vault_transfer.py', 'login_startup.py',
               'vision_mcp.py', 'chat_attachments.py', 'webui_attachments_filter.py', 'attachment_setup.py', 'file_workflows.py', 'scheduled_tasks.py', 'autonomous_jobs.py', 'service_lifecycle.py', 'webui_local_images.py', 'required_tools_setup.py', 'native_pdf_loader.py', 'capability_acceptance.py',
              'control_policy.py', 'delegation_browser.py', 'automation_mcp.py', 'automation_setup.py', 'automation_check.py', 'automation-guard.mjs',
              'essay-edit.mjs', 'essay-edit-prompt.txt', 'essay_setup.py',
              'reverse-scaffold.mjs', 'reverse-scaffold-prompt.txt', 'scaffold_setup.py', 'discord_setup.py', 'discord_runtime.py', 'discord-adapter.mjs', 'discord-core.mjs',
              'discord-package.json', 'discord-package-lock.json', 'conversation_setup.py', 'conversation.py', 'conversation_check.py', 'conversation.html', 'conversation.mjs', 'microphone.js')
TEAM_FILES += ('captain.mjs', 'captain-runtime.mjs', 'captain_setup.py', 'captain_check.py')
MODELS = [
    ("checkpoints/sd_xl_base_1.0.safetensors",
     "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
     "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b"),
    ("checkpoints/ltx-video-2b-v0.9.5.safetensors",
     "https://huggingface.co/Lightricks/LTX-Video/resolve/main/ltx-video-2b-v0.9.5.safetensors",
     "720d15c9f19f7d0f6b2a92bbbc34410e2cfb2f6856a100b38f734fbf973d4adf"),
    ("text_encoders/t5xxl_fp16.safetensors",
     "https://huggingface.co/Comfy-Org/mochi_preview_repackaged/resolve/main/split_files/text_encoders/t5xxl_fp16.safetensors",
     "6e480b09fae049a72d2a8c5fbccb8d3e92febeb233bbe9dfe7256958a9167635"),
]


def run(command, **kwargs):
    logging.info("Running %s", Path(str(command[0])).name)
    subprocess.run([str(value) for value in command], check=True, **kwargs)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        while block := source.read(8 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def download(url, destination, checksum=None):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if checksum is None or digest(destination) == checksum:
            logging.info("Reusing %s", destination.name)
            return
        invalid = destination.with_name(destination.name + ".invalid-" + str(time.time_ns()))
        destination.rename(invalid)
        logging.warning("Preserved invalid download as %s", invalid.name)
    partial = destination.with_name(destination.name + ".part")
    logging.info("Downloading %s; interrupted downloads can resume", destination.name)
    run(["/usr/bin/curl", "-fL", "--retry", "3", "--retry-delay", "3",
         "--connect-timeout", "30", "-C", "-", "-o", partial, url])
    if checksum and digest(partial) != checksum:
        invalid = partial.with_name(partial.name + ".invalid-" + str(time.time_ns()))
        partial.rename(invalid)
        raise RuntimeError(f"Checksum failed for {destination.name}; invalid data preserved, not installed.")
    partial.replace(destination)


def extract_zip(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("Archive contains a path outside its extraction directory.")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Source archive contains an unexpected symbolic link.")
        zipped.extractall(destination)


def checkpoint(path, stage):
    state = json.loads(path.read_text()) if path.exists() else {"completed": []}
    if stage not in state["completed"]:
        state["completed"].append(stage)
    state["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(path)


def completed(path, stage):
    return path.exists() and stage in json.loads(path.read_text()).get("completed", [])


def acceptance_fingerprint(root):
    hashes = [digest(root / "control" / name) for name in
              GATEWAY_FILES + TEAM_FILES + ("workflows/image.json", "workflows/video.json", "config.json", "comfy_vault/__init__.py")]
    # Registering/changing the reference must invalidate an earlier not_run speech check.
    for name in ('voices/default.json', 'voices/default.wav', 'installed.json', 'conversation-installed.json'):
        path = root / 'voice-engine' / name
        hashes.append(digest(path) if path.is_file() else 'missing:' + name)
    return hashlib.sha256("\n".join(hashes + [COMFY_RELEASE, WEBUI_RELEASE]).encode()).hexdigest()


def preflight(root):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Requires Apple Silicon running native arm64 macOS, not Intel/Rosetta.")
    version = tuple(int(part) for part in platform.mac_ver()[0].split(".")[:2])
    if version < (15, 0):
        raise RuntimeError("This installer targets macOS 15 or newer. Update macOS first.")
    memory = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
    if memory < 32 * 1024**3:
        raise RuntimeError("This model selection requires at least 32GB unified memory.")
    first_install = not (root / "install-state.json").exists()
    minimum_free = (100 if first_install else 20) * 1024**3
    if shutil.disk_usage(root).free < minimum_free:
        raise RuntimeError(f"Need at least {minimum_free // 1024**3}GB free SSD space for this installation stage.")
    for service, port in PORTS.items():
        if port_open(port):
            raise RuntimeError(f"{service} port {port} is already in use. Close that Local AI instance first.")
    logging.info("Hardware checks passed: %.0fGB unified memory", memory / 1024**3)


def ollama_client_version(binary, root):
    output = subprocess.check_output([str(binary), '--version'], env=ollama_environment(root),
                                     stderr=subprocess.STDOUT, text=True, timeout=15)
    # The private daemon is stopped; prefer the CLI version over another server.
    match = re.search(r'client version is (\S+)', output) or re.search(r'ollama version is (\S+)', output)
    if not match:
        raise RuntimeError('Could not identify the private Ollama version')
    return require_backend_version(match.group(1))


def install_ollama(root):
    binary = ollama_binary(root)
    if binary.exists():
        try:
            ollama_client_version(binary, root)
            return
        except (RuntimeError, subprocess.SubprocessError):
            logging.info('Upgrading the private Ollama copy for native context protection')
    archive = root / f"cache/Ollama-{OLLAMA_CONTEXT_RELEASE}-darwin.zip"
    download(f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_CONTEXT_RELEASE}/Ollama-darwin.zip",
             archive, OLLAMA_CONTEXT_SHA256)
    with tempfile.TemporaryDirectory(dir=root / "cache") as directory:
        # ditto preserves framework links and code-signing metadata in the official app archive.
        with zipfile.ZipFile(archive) as zipped:
            for name in zipped.namelist():
                if not (Path(directory) / name).resolve().is_relative_to(Path(directory).resolve()):
                    raise RuntimeError("Ollama archive contains an invalid path.")
        run(["/usr/bin/ditto", "-xk", archive, directory])
        candidates = list(Path(directory).glob("**/Ollama.app"))
        if len(candidates) != 1:
            raise RuntimeError("Official Ollama download has changed layout; installation stopped.")
        app = candidates[0]
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", app])
        if not (app / "Contents/Resources/ollama").is_file():
            raise RuntimeError("Official Ollama archive no longer contains the expected CLI binary.")
        ollama_client_version(app / 'Contents/Resources/ollama', root)
        previous = root / 'tools/Ollama.app'
        backup = None
        if previous.exists():
            backup = root / ('tools/Ollama.app.before-context-' + str(time.time_ns()))
            previous.rename(backup)
        try:
            shutil.move(str(app), previous)
        except Exception:
            if backup is not None and not previous.exists():
                backup.rename(previous)
            raise


def install_comfy(root, uv, state):
    directory = root / "ComfyUI"
    if not (directory / "main.py").exists():
        archive = root / "cache/ComfyUI.zip"
        download(f"https://github.com/Comfy-Org/ComfyUI/archive/refs/tags/{COMFY_RELEASE}.zip", archive)
        with tempfile.TemporaryDirectory(dir=root / "cache") as temporary:
            extract_zip(archive, temporary)
            sources = [p for p in Path(temporary).iterdir() if p.is_dir() and (p / "main.py").is_file()]
            if len(sources) != 1:
                raise RuntimeError("ComfyUI source archive layout has changed.")
            shutil.move(str(sources[0]), directory)
    python = directory / ".venv/bin/python"
    environment_missing = not python.exists()
    if environment_missing:
        run([uv, "venv", "--python", "3.12", directory / ".venv"])
    if environment_missing or not completed(state, "comfy-dependencies"):
        run([uv, "pip", "install", "--python", python, "torch", "torchvision", "torchaudio"])
        run([uv, "pip", "install", "--python", python, "-r", directory / "requirements.txt"])
        checkpoint(state, "comfy-dependencies")
    run([python, "-c", "import platform, torch; assert platform.machine() == 'arm64'; assert torch.backends.mps.is_available(), 'Apple GPU MPS is unavailable'; print('Apple GPU MPS: available')"])
    return directory


def install_environments(root, uv, state):
    control = root / "control"
    control.mkdir(exist_ok=True)
    # Remove only explicitly retired project files, never user data/workflows.
    for name in ("tool_registry.py", "tool_executor.py", "tool_loop.py", "github_adapter.py", "github_mcp.py",
                 "tests/test_tools.py", "tests/test_web_tools.py", "tests/test_github.py"):
        (control / name).unlink(missing_ok=True)
    for name in GATEWAY_FILES + ("check-workflows.py", "requirements.txt"):
        shutil.copy2(SOURCE / "payload" / name, control / name)
    shutil.copytree(SOURCE / "payload/tests", control / "tests", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Preserve workflow edits on subsequent installer runs.
    if not (control / "workflows").exists():
        shutil.copytree(SOURCE / "payload/workflows", control / "workflows")
    for name in ("runtime.py", "common.py", "context_settings.py", "remote_access.py", "web_access.py", "reverse_image_setup.py", "workspace_setup.py", "account_tools.py", "vault_backup.py", "mode_selector.py", "work_agent.py"):
        shutil.copy2(SOURCE / name, control / name)
    for name in TEAM_FILES:
        shutil.copy2(SOURCE / name, control / name)
    shutil.copytree(SOURCE / "web", control / "web", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Install only our descriptor-based save nodes; vault-mode CLI disables every
    # other external node. Keep the bundled copy in control for repair/checks.
    shutil.copytree(SOURCE / 'comfy_vault', root / 'ComfyUI/custom_nodes/local_ai_vault',
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(SOURCE / 'comfy_vault', control / 'comfy_vault',
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    python = control / ".venv/bin/python"
    if not python.exists():
        run([uv, "venv", "--python", "3.11", control / ".venv"])
    run([uv, "pip", "install", "--python", python, "Pillow>=11,<13", "requests>=2.32,<3", "imageio-ffmpeg==0.6.0"])
    run([python, "-c", "import imageio_ffmpeg, subprocess; subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-version'], check=True)"])
    run([python, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=control)
    webui = root / "webui"
    (webui / "data").mkdir(parents=True, exist_ok=True)
    webui_missing = not (webui / ".venv/bin/python").exists()
    if webui_missing:
        run([uv, "venv", "--python", "3.11", webui / ".venv"])
    if webui_missing or not completed(state, "webui-dependencies"):
        run([uv, "pip", "install", "--python", webui / ".venv/bin/python", f"open-webui=={WEBUI_RELEASE}"])
        checkpoint(state, "webui-dependencies")
    from webui_local_images import harden, harden_pdf
    harden(root)
    harden_pdf(root)
    config_path = control / "config.json"
    if not config_path.exists():
        config = {"comfy_dir": str(root / "ComfyUI"), "text_model": "qwen3:14b",
                  "thinking": False, "render_timeout_seconds": 3600,
                  "api_key": secrets.token_urlsafe(32), "webui_secret": secrets.token_urlsafe(48),
                  "ollama_url": "http://127.0.0.1:11435", "comfy_url": "http://127.0.0.1:8189",
                  "gateway_port": 8001, "public_url": "http://127.0.0.1:8001"}
        config_path.write_text(json.dumps(config, indent=2) + "\n")
        config_path.chmod(0o600)
    config = json.loads(config_path.read_text())
    from captain_config import upgrade as upgrade_captain
    upgraded = upgrade_captain(upgrade_team(upgrade_text_configuration(config)))
    from voice_setup import install as install_voice
    upgraded['speech'] = install_voice(root, uv, run)
    from conversation_setup import install as install_conversation
    upgraded['conversation'] = install_conversation(root, uv, run)
    if upgraded != config:
        # Keep the old settings and secrets recoverable before migrating.
        backup = config_path.with_name("config.before-model-team-v1.json")
        if not backup.exists():
            backup.write_text(json.dumps(config, indent=2) + "\n")
            backup.chmod(0o600)
        temporary = config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(upgraded, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(config_path)
    return upgraded


def verify_text_cutoff(key, identifier):
    """Exercise native output exhaustion, not just a one-sentence smoke test."""
    response = http('http://127.0.0.1:8001/v1/chat/completions',
                    {'model': identifier, 'stream': False, 'max_completion_tokens': 8,
                     'messages': [{'role': 'user', 'content':
                                   'Write a detailed 2000-word essay about the history of computing.'}]},
                    key=key, timeout=4000)
    reason = response['choices'][0]['finish_reason']
    if reason != 'length':
        raise RuntimeError(f'{identifier}: output-cutoff acceptance did not report length; check the installed Ollama backend.')
    return {'finish_reason': reason, 'usage': response.get('usage', {})}


def verify_context_rejection(key, identifier, context):
    """Prove oversized inputs are rejected, including history and tool envelopes."""
    large = ' x' * max(context * 4, 4096)
    tool = {'type': 'function', 'function': {'name': 'read_text', 'description': 'Read text',
                                           'parameters': {'type': 'object', 'properties': {}}}}
    cases = [
        ('first-message', [{'role': 'user', 'content': large}], []),
        ('old-history', [{'role': 'system', 'content': 'Keep all instructions.'},
                         {'role': 'user', 'content': large}, {'role': 'assistant', 'content': 'Recorded.'},
                         {'role': 'user', 'content': 'Reply briefly using the earlier information.'}], []),
        ('tool-result', [{'role': 'user', 'content': 'Read the document.'},
                         {'role': 'assistant', 'content': None, 'tool_calls': [
                             {'id': 'acceptance-read', 'type': 'function', 'function':
                              {'name': 'read_text', 'arguments': '{}'}}]},
                         {'role': 'tool', 'tool_call_id': 'acceptance-read', 'content': large},
                         {'role': 'user', 'content': 'Summarise it.'}], [tool]),
        ('tool-schema', [{'role': 'user', 'content': 'Reply briefly.'}], [
            {'type': 'function', 'function': dict(tool['function'], description=large)}]),
    ]
    results = []
    for name, messages, tools in cases:
        body = {'model': identifier, 'messages': messages, 'stream': False,
                'max_completion_tokens': 1, 'tools': tools}
        try:
            http('http://127.0.0.1:8001/v1/chat/completions', body, key=key, timeout=4000)
        except HTTPError as error:
            payload = json.loads(error.read(8192))
            if error.code != 400 or payload.get('error', {}).get('code') != 'context_length_exceeded':
                raise RuntimeError(f'{identifier}/{name}: context acceptance returned an unexpected error') from None
            results.append({'case': name, 'status': 'passed', 'code': 'context_length_exceeded'})
        else:
            raise RuntimeError(f'{identifier}/{name}: oversized input was accepted; native context protection is not verified')
    return results


def verify_generation(root, configuration):
    import resource_modes
    if resource_modes.load(root / "control") != "max":
        raise RuntimeError("Full hardware acceptance requires Max mode. Select Max in AI Modes, stop Local AI, then rerun the installer.")
    processes = []
    control = root / "control"
    try:
        ollama = launch([ollama_binary(root), "serve"], root, root / "logs/ollama.log", ollama_environment(root))
        processes.append(ollama)
        wait_ready("http://127.0.0.1:11435/api/version", ollama)
        if configuration.get('captain', {}).get('enabled') and configuration['captain'].get('provider', 'ollama') == 'ollama':
            shared = launch([ollama_binary(root), 'serve'], root, root / 'logs/shared-text.log',
                            ollama_environment(root, parallel=configuration['captain']['max_parallel'], port=11436))
            processes.append(shared)
            wait_ready('http://127.0.0.1:11436/api/version', shared)
        presets = configured_text_models(configuration)
        from team_setup import prepare_models
        prepare_models(root, presets, download, run, http)
        run([control / ".venv/bin/python", control / "check-workflows.py"], cwd=control)
        gateway = launch([control / ".venv/bin/python", control / "gateway.py"], control,
                         root / "logs/gateway.log", os.environ.copy())
        processes.append(gateway)
        wait_ready("http://127.0.0.1:8001/health", gateway)
        webui = launch([root / "webui/.venv/bin/open-webui", "serve", "--host", "127.0.0.1", "--port", "8081"],
                       root / "webui", root / "logs/webui.log", webui_environment(root, configuration))
        processes.append(webui)
        wait_ready("http://127.0.0.1:8081/health", webui, timeout=600)
        ContextSettings().sync(http('http://127.0.0.1:8001/control/context', key=configuration['api_key']))
        checks = [("text-" + identifier, "Reply with one sentence about Python.", identifier)
                  for identifier in presets]
        checks += [(kind, prompt, "local-ai") for kind, prompt in [
            ("text", "Reply with one sentence about Python."),
            ("image", "/image A red toy racing car on a white table, studio photograph, no text."),
            ("text-after-image", "Reply with one sentence about statistics."),
            ("video", "/video A fixed camera watches a red toy racing car move slowly from left to right on a white table. The wheels rotate naturally. Soft studio light and a plain background. Stable camera, no text or logos."),
            ("text-after-video", "Reply with one sentence about reproducibility."),
        ]]
        report = {"tested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "checks": [], "media": "vault-direct" if configuration.get("vault", {}).get("enabled") else "local"}
        if configuration.get('model_team', {}).get('enabled'):
            report['checks'].append({'name': 'reverse-scaffold-quality', 'status': 'not_run',
                'reason': 'Stage and schema tests use simulated responses. Author must check actual local-model planning quality on the Mac.'})
            report['checks'].append({'name': 'essay-edit-quality', 'status': 'not_run',
                'reason': 'Host contract tests use simulated edits. Complete ESSAY-EDITING.md acceptance on the installed document model.'})
        if configuration.get('discord', {}).get('enabled'):
            report['checks'].append({'name': 'discord-live-call', 'status': 'not_run',
                'reason': 'Dependencies and account setup checked. Complete the live voice, interruption, permissions and Gaming-mode checks in DISCORD.md.'})
        if configuration.get('conversation', {}).get('enabled'):
            report['checks'].append({'name': 'interactive-conversation', 'status': 'not_run',
                'reason': 'Audio workers load-checked during installation. Run Check Conversation.command, then the microphone, interruption, approvals and memory checks in REALTIME-CONVERSATION.md.'})
        if configuration.get('speech', {}).get('enabled'):
            if (root / 'voice-engine/voices/default.json').exists():
                checks += [('speech', '/speak This is a local speech generation acceptance test.', 'local-ai-small'),
                           ('text-after-speech', 'Reply with one sentence about audio.', 'local-ai-small')]
            else:
                report['checks'].append({'name': 'speech-generation', 'status': 'not_run',
                    'reason': 'Base model loaded by voice installation, but no reference voice registered. Configure Voice.command, then rerun acceptance.'})
        for kind, prompt, identifier in checks:
            logging.info("Hardware acceptance test: %s. Video may take a long time.", kind)
            started = time.monotonic()
            response = http("http://127.0.0.1:8001/v1/chat/completions",
                            {"model": identifier, "stream": False,
                             "messages": [{"role": "user", "content": prompt}]},
                            key=configuration["api_key"], timeout=4000)
            content = response["choices"][0]["message"]["content"]
            if not content.strip():
                raise RuntimeError(f"{kind} returned an empty answer.")
            if kind.startswith("text"):
                loaded = http("http://127.0.0.1:11435/api/ps").get("models", [])
                expected = presets[identifier]["model"]
                if any(model["name"] != expected for model in loaded):
                    raise RuntimeError("A different text model remained loaded after model switching.")
            if kind in {"image", "video", "speech"}:
                extension = '.wav' if kind == 'speech' else ".png" if kind == "image" else ".mp4"
                if extension not in content:
                    raise RuntimeError(f"{kind} did not return the expected saved output.")
                if http("http://127.0.0.1:11435/api/ps").get("models"):
                    raise RuntimeError("Text model remained loaded after a visual job.")
                if port_open(PORTS["comfy"]):
                    raise RuntimeError("ComfyUI remained running after its visual job.")
            report["checks"].append({"name": kind, "model_id": identifier,
                                     "seconds": round(time.monotonic() - started, 1),
                                     "status": "passed", "result": content})
            if kind == 'text-' + identifier:
                cutoff = verify_text_cutoff(configuration['api_key'], identifier)
                report['checks'].append({'name': 'cutoff-' + identifier, 'model_id': identifier,
                                         'status': 'passed', **cutoff})
                context_checks = verify_context_rejection(configuration['api_key'], identifier, presets[identifier]['num_ctx'])
                report['checks'].append({'name': 'context-' + identifier, 'model_id': identifier,
                                         'status': 'passed', 'cases': context_checks})
            (root / "acceptance-report.json").write_text(json.dumps(report, indent=2) + "\n")
        from team_setup import verify_native_handoffs
        report['checks'].extend(verify_native_handoffs(root, configuration))
        from captain_check import verify as verify_captain
        report['checks'].extend(verify_captain(root, configuration))
        (root / "acceptance-report.json").write_text(json.dumps(report, indent=2) + "\n")
    finally:
        for process in reversed(processes):
            stop_process(process, timeout=4200)


def make_launcher(root):
    command = root / "Start Local AI.command"
    command.write_text("#!/bin/bash\nset -e\ncd " + shlex.quote(str(root / "control")) +
                       "\nexec .venv/bin/python runtime.py\n")
    command.chmod(0o755)
    for label, argument in (("Enable Web Access", ""), ("Disable Web Access", " --disable")):
        web_command = root / (label + ".command")
        web_command.write_text("#!/bin/bash\nset -e\ncd " + shlex.quote(str(root / "control")) +
                              "\nexec .venv/bin/python web_access.py --root " + shlex.quote(str(root)) + argument + "\n")
        web_command.chmod(0o755)
    for label, argument in (("Enable Browser", ""), ("Disable Browser", " --disable"), ("Check Browser", " --check")):
        helper = root / (label + ".command")
        helper.write_text("#!/bin/bash\nset -e\ncd " + shlex.quote(str(root / "control")) +
                          "\nexec .venv/bin/python browser_setup.py --root " + shlex.quote(str(root)) + argument + "\n")
        helper.chmod(0o755)
    for label, module in (("Read PDF", "pdf_reader.py"), ("File Transfer", "file_transfer.py")):
        helper = root / (label + ".command")
        helper.write_text("#!/bin/bash\nset -e\ncd " + shlex.quote(str(root / "control")) +
                          "\nexec .venv/bin/python " + module + " \"$@\"\n")
        helper.chmod(0o755)
    helper = root / 'Stop Local AI.command'
    helper.write_text('#!/bin/bash\nset -e\ncd ' + shlex.quote(str(root / 'control')) +
                      '\nexec .venv/bin/python service_lifecycle.py --root ' + shlex.quote(str(root)) + '\n')
    helper.chmod(0o755)
    for label, argument in (("Enable Login Startup", ""), ("Disable Login Startup", " --disable")):
        helper = root / (label + ".command")
        helper.write_text("#!/bin/bash\nset -e\ncd " + shlex.quote(str(root / "control")) +
                          "\nexec .venv/bin/python login_startup.py --root " + shlex.quote(str(root)) + argument + "\n")
        helper.chmod(0o755)
    for label, argument in (('Schedule AI Task', '--configure'), ('Scheduled Task Status', '--status'), ('Remove Scheduled Task', '--remove')):
        helper = root / (label + '.command')
        helper.write_text('#!/bin/bash\nset -e\ncd ' + shlex.quote(str(root / 'control')) +
                          '\nexec .venv/bin/python scheduled_tasks.py --root ' + shlex.quote(str(root)) + ' ' + argument + '\n')
        helper.chmod(0o755)
    for label, argument in (('Create Autonomous Job', '--configure'), ('Autonomous Job Status', '--status'),
                            ('Stop Autonomous Job', '--stop'), ('Resume Autonomous Job', '--resume')):
        helper = root / (label + '.command')
        helper.write_text('#!/bin/bash\nset -e\ncd ' + shlex.quote(str(root / 'control')) +
                          '\nexec .venv/bin/python autonomous_jobs.py --root ' +
                          shlex.quote(str(root)) + ' ' + argument + ' "$@"\n')
        helper.chmod(0o755)
    helper = root / 'Check Tool Availability.command'
    helper.write_text('#!/bin/bash\nset -e\ncd ' + shlex.quote(str(root / 'control')) +
                      '\nexec .venv/bin/python tool_availability.py --root ' + shlex.quote(str(root)) + '\n')
    helper.chmod(0o755)
    helper = root / 'Check Required Capabilities.command'
    helper.write_text('#!/bin/bash\nset -e\ncd ' + shlex.quote(str(root / 'control')) +
                      '\nexec .venv/bin/python capability_acceptance.py --root ' + shlex.quote(str(root)) + '\n')
    helper.chmod(0o755)
    for label, argument in (("Enable Desktop Control", "--desktop"), ("Enable External Delegation", "--delegation"),
                            ("Disable Scoped Automation", "--disable"), ("Stop Automation", "--stop"),
                            ("Rearm Automation", "--rearm")):
        helper = root / (label + ".command")
        helper.write_text("#!/bin/bash\nset -e\ncd " + shlex.quote(str(root / "control")) +
                          "\nexec .venv/bin/python automation_setup.py --root " + shlex.quote(str(root)) + " " + argument + "\n")
        helper.chmod(0o755)
    for label, argument in (("Check Desktop Control", ""), ("Check External Delegation", " --external")):
        helper = root / (label + ".command")
        helper.write_text("#!/bin/bash\nset -e\ncd " + shlex.quote(str(root / "control")) +
                          "\nexec .venv/bin/python automation_check.py --root " + shlex.quote(str(root)) + argument + "\n")
        helper.chmod(0o755)
    for label, argument in (("Enable Remote Access", ""), ("Disable Remote Access", " --disable")):
        remote_command = root / (label + ".command")
        remote_command.write_text("#!/bin/bash\nset -e\ncd " + shlex.quote(str(root / "control")) +
                                 "\nexec .venv/bin/python remote_access.py --root " + shlex.quote(str(root)) +
                                 argument + "\n")
        remote_command.chmod(0o755)
    for label, module in (("Check Office", "office_setup.py"), ("Check Captain", "captain_check.py"), ("Install MiniCPM Captain", "captain_setup.py --install-minicpm"), ("Scaffold Essay", "work_agent.py --scaffold"), ("Edit Essay", "work_agent.py --essay"), ("Connect Discord", "discord_setup.py"), ("Check Conversation", "conversation_check.py"), ("Start Conversation", "work_agent.py --conversation"), ("Configure Voice", "voice_setup.py"), ("Start Work Agent", "work_agent.py"), ("AI Modes", "mode_selector.py"), ("Configure AI Workspace", "workspace_setup.py"), ("Configure Reverse Image Search", "reverse_image_setup.py"), ("Disable Reverse Image Search", "reverse_image_setup.py --disable"), ("Connect GitHub", "account_tools.py"), ("Back Up AI Workspace", "vault_backup.py"),
                         ("Restore AI Workspace", "vault_backup.py --restore"), ("Archive Existing AI Files", "vault_backup.py --migrate-legacy")):
        helper = root / (label + '.command')
        helper.write_text('#!/bin/bash\nset -e\ncd ' + shlex.quote(str(root / 'control')) +
                          '\nexec .venv/bin/python ' + module + ' --root ' + shlex.quote(str(root)) + '\n')
        helper.chmod(0o755)
    application = Path.home() / "Applications/Local AI.app"
    if application.exists() and not (application / "Contents/local-ai-owner.txt").exists():
        raise RuntimeError("An unrelated Local AI.app already exists. No application was overwritten.")
    (application / "Contents/MacOS").mkdir(parents=True, exist_ok=True)
    (application / "Contents/local-ai-owner.txt").write_text(str(root))
    executable = application / "Contents/MacOS/LocalAI"
    executable.write_text("#!/bin/bash\nexec /usr/bin/open -a Terminal " + shlex.quote(str(command)) + "\n")
    executable.chmod(0o755)
    with (application / "Contents/Info.plist").open("wb") as output:
        plistlib.dump({"CFBundleName": "Local AI", "CFBundleDisplayName": "Local AI",
                      "CFBundleExecutable": "LocalAI", "CFBundleIdentifier": "local.mac.ai.personal",
                      "CFBundleVersion": "1", "CFBundlePackageType": "APPL"}, output)
    return application


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--remote-access", action="store_true",
                        help="Install/connect Tailscale and configure private chat/media HTTPS access.")
    parser.add_argument("--web-access", action="store_true", help="Configure isolated Proton VPN search/page reading.")
    parser.add_argument('--minicpm-captain', action='store_true',
                        help='Build the pinned native MiniCPM runtime and use its standard mixed-Q3 model as the shared team.')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("logs", "cache", "tools", "models/ollama"):
        (root / name).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(root / "logs/install.log")])
    lock = (root / ".installer.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another copy of the installer is running.")
    state = root / "install-state.json"
    try:
        logging.info("Stage 1/8: hardware and port checks")
        preflight(root)
        logging.info("Stage 2/8: native Ollama installation")
        install_ollama(root)
        checkpoint(state, "ollama-installed")
        logging.info("Stage 3/8: ComfyUI and Apple GPU support")
        install_comfy(root, args.uv, state)
        logging.info("Stage 4/8: verified image/video model downloads")
        for relative, url, checksum in MODELS:
            download(url, root / "ComfyUI/models" / relative, checksum)
        logging.info("Stage 5/8: gateway and automatically configured chat UI")
        configuration = install_environments(root, args.uv, state)
        from workspace_setup import install_cryptomator, save_config
        app = install_cryptomator(root, download, run)
        from work_agent import install as install_work_agent
        install_work_agent(root, download, run)
        from office_setup import install as install_office
        configuration['office'] = install_office(root, download, run)
        configuration['cryptomator_app'] = str(app)
        save_config(root, configuration)
        from discord_setup import install as install_discord, configure as configure_discord
        install_discord(root, download, run)
        configure_discord(root)
        configuration = json.loads((root / 'control/config.json').read_text())
        if args.minicpm_captain:
            from captain_setup import install_minicpm
            configuration = install_minicpm(root, download)
        logging.info("Stage 6/8: hardware generation and memory handoff tests")
        fingerprint = acceptance_fingerprint(root)
        accepted_file = root / "accepted-fingerprint.txt"
        if (not completed(state, "hardware-acceptance") or not accepted_file.exists()
                or accepted_file.read_text() != fingerprint):
            verify_generation(root, configuration)
            accepted_file.write_text(fingerprint)
            checkpoint(state, "hardware-acceptance")
        else:
            logging.info("Reusing the successful hardware acceptance report.")
        logging.info("Stage 7/8: create daily launcher and record versions")
        application = make_launcher(root)
        for directory in (root / "ComfyUI", root / "control", root / "webui"):
            with (directory / "installed-versions.txt").open("w") as output:
                run([args.uv, "pip", "freeze", "--python", directory / ".venv/bin/python"], stdout=output)
        (root / "software-versions.json").write_text(json.dumps(
            {"comfyui": COMFY_RELEASE, "open_webui": WEBUI_RELEASE, "opencode": "1.18.34",
             "aioffice": configuration['office']['version'],
             "text_models": configured_text_models(configuration)}, indent=2))
        checkpoint(state, "installed")
        if args.web_access:
            from web_access import configure as configure_web
            configure_web(root)
            checkpoint(state, "web-access-configured")
        if args.remote_access:
            logging.info("Optional remote-access stage: Tailscale sign-in and private HTTPS proxies")
            from remote_access import configure
            configure(root)
            checkpoint(state, "remote-access-configured")
        print('Cryptomator is installed. Close Local AI and run Configure AI Workspace.command to register your vault.')
        print('Run Connect GitHub.command to add your account. Neither helper receives your vault password.')
        logging.info("Stage 8/8: launching Local AI")
        logging.info("Daily launcher: %s", application)
        runtime_python = str(root / "control/.venv/bin/python")
        os.execv(runtime_python, [runtime_python, str(root / "control/runtime.py")])
    except (Exception, KeyboardInterrupt) as error:
        logging.exception("INSTALLATION STOPPED: %s", error)
        print("\nInstallation stopped. Completed files/stages are preserved.")
        print("Run the same installer again to resume. Details:", root / "logs/install.log")
        return 1
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())


