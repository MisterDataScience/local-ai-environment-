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
# Immutable source revision behind v0.38.0. Never download floating refs/tags.
COMFY_COMMIT = "6b747c0428c343e1417219641db93a4fb7cb69ae"
COMFY_SHA256 = "4a144a553c77397c81f6067f3f8c8ab9dffd42889af48fb35fec2c64a71c75b2"
TORCH_VERSION = "2.10.0"
TORCHVISION_VERSION = "0.25.0"
TORCHAUDIO_VERSION = "2.10.0"
WEBUI_RELEASE = "0.11.1"
OLLAMA_CONTEXT_RELEASE = '0.40.0'
OLLAMA_CONTEXT_SHA256 = '60dd339e77fdc8afe3286c51ff1fd8eb4f467ec178f33f4a85ec69dac6f2b9dd'
GATEWAY_FILES = ("gateway.py", "backend_http.py", "routing.py", "workflows.py",
                 "model_engine.py", "http_api.py", "text_models.py", "web_client.py",
                 "tool_protocol.py", "image_inputs.py", "web_tools_api.py", "reverse_image.py", "vault_tools.py", "vault_media.py", "resource_modes.py", "context_policy.py", "model_team.py", "speech.py", "speech_worker.py")
GATEWAY_FILES += ('token_stream.py', 'conversation_audio.py', 'conversation_worker.py')
GATEWAY_FILES += ('capability_discovery.py',)
GATEWAY_FILES += ('inference_scheduler.py', 'captain_config.py', 'shared_llama.py')
GATEWAY_FILES += ('commons_transport.py', 'commons.html')
GATEWAY_FILES += ('institutions.html',)
TEAM_FILES = ('work_agent.py', 'opencode-team.mjs', 'handoff-contract.mjs', 'native_session_store.py', 'team_setup.py', 'voice_setup.py',
              'office_setup.py', 'office_mcp.py', 'office_check.py', 'browser_agent.py', 'browser_setup.py',
               'tool_availability.py', 'pdf_reader.py', 'pdf_mcp.py', 'transfer_mcp.py', 'file_transfer.py', 'vault_transfer.py', 'login_startup.py',
               'vision_mcp.py', 'chat_attachments.py', 'webui_attachments_filter.py', 'attachment_setup.py', 'file_workflows.py', 'scheduled_tasks.py', 'autonomous_jobs.py', 'service_lifecycle.py', 'webui_local_images.py', 'required_tools_setup.py', 'native_pdf_loader.py', 'capability_acceptance.py',
              'control_policy.py', 'delegation_browser.py', 'automation_mcp.py', 'automation_setup.py', 'automation_check.py', 'automation-guard.mjs',
              'essay-edit.mjs', 'essay-edit-prompt.txt', 'essay_setup.py',
              'reverse-scaffold.mjs', 'reverse-scaffold-prompt.txt', 'scaffold_setup.py', 'discord_setup.py', 'discord_runtime.py', 'discord-adapter.mjs', 'discord-core.mjs',
              'discord-package.json', 'discord-package-lock.json', 'conversation_setup.py', 'conversation.py', 'conversation_check.py', 'conversation.html', 'conversation.mjs', 'microphone.js')
TEAM_FILES += ('native_diagnostics.py', 'diagnose_captain.py', 'captain_conversation_check.py')
TEAM_FILES += ('captain.mjs', 'captain-runtime.mjs', 'captain_setup.py', 'captain_check.py', 'acceptance_diagnostics.py', 'managed_captain.py', 'workspace_install.py', 'docker_setup.py', 'power_guard.py', 'remote_recovery.py', 'dependency_locks.py', 'village.py', 'village_infrastructure.py')
TEAM_FILES += ('commons.py', 'commons_control.py', 'village_memory.py', 'resident_management.py', 'village_storage.py', 'founding.py', 'village_owner.py')
TEAM_FILES += ('studio_store.py','studio_runtime.py','studio_workbench.py','studio_player.py','studio_control.py','studios.py','studio_roles.py')
TEAM_FILES += ('synod.py','synod_store.py')
TEAM_FILES += ('feature_state.py', 'feature_install.py', 'feature_checks.py', 'installer.py', 'turnkey_install.py')
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
    if destination.is_symlink():
        raise RuntimeError("Refusing symbolic link as install download destination: " + destination.name)
    if destination.exists():
        if checksum is None or digest(destination) == checksum:
            logging.info("Reusing %s", destination.name)
            return
        invalid = destination.with_name(destination.name + ".invalid-" + str(time.time_ns()))
        destination.rename(invalid)
        logging.warning("Preserved invalid download as %s", invalid.name)
    partial = destination.with_name(destination.name + ".part")
    if partial.is_symlink():
        raise RuntimeError("Refusing symlink for interrupted download " + destination.name)
    if partial.is_file():
        # A previous run can complete the transfer and be interrupted before
        # the final rename. Retrying an already-complete HTTP range may return
        # 416 and block every subsequent installation attempt.
        if checksum and digest(partial) == checksum:
            logging.info("Promoting already-verified interrupted download %s", destination.name)
            partial.replace(destination)
            return
        if checksum is None and destination.suffix.lower() == ".zip" and zipfile.is_zipfile(partial):
            with zipfile.ZipFile(partial) as archive:
                if archive.testzip() is None:
                    logging.info("Promoting complete cached ZIP %s", destination.name)
                    partial.replace(destination)
                    return
    logging.info("Downloading %s; interrupted downloads can resume", destination.name)
    command = ["/usr/bin/curl", "-fL", "--proto", "=https", "--proto-redir", "=https",
               "--retry", "3", "--retry-delay", "3", "--connect-timeout", "30"]
    try:
        run(command + ["-C", "-", "-o", partial, url])
    except subprocess.CalledProcessError as error:
        # A server may reject Range, or a complete corrupt partial may return
        # HTTP 416. Retry once without Range instead of trapping every rerun.
        if error.returncode not in {22, 33, 36} or not partial.is_file():
            raise
        run(command + ["-o", partial, url])
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
    # Changing a deployed dependency lock invalidates earlier native acceptance.
    for path in sorted((root / 'control/locks').glob('*.txt')):
        hashes.append(digest(path))
    for path in sorted((root / 'control/studio_sdk').glob('*')):
        if path.is_file():hashes.append(digest(path))
    # Registering/changing the reference must invalidate an earlier not_run speech check.
    for name in ('voices/default.json', 'voices/default.wav', 'installed.json', 'conversation-installed.json'):
        path = root / 'voice-engine' / name
        hashes.append(digest(path) if path.is_file() else 'missing:' + name)
    return hashlib.sha256("\n".join(hashes + [COMFY_RELEASE, COMFY_COMMIT, TORCH_VERSION, TORCHVISION_VERSION, TORCHAUDIO_VERSION, WEBUI_RELEASE]).encode()).hexdigest()


def preflight(root, *, core=False):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Requires Apple Silicon running native arm64 macOS, not Intel/Rosetta.")
    version = tuple(int(part) for part in platform.mac_ver()[0].split(".")[:2])
    if version < (15, 0):
        raise RuntimeError("This installer targets macOS 15 or newer. Update macOS first.")
    memory = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
    if memory < 32 * 1024**3:
        raise RuntimeError("This model selection requires at least 32GB unified memory.")
    first_install = not (root / "install-state.json").exists()
    minimum_free = ((35 if core else 100) if first_install else 20) * 1024**3
    if shutil.disk_usage(root).free < minimum_free:
        raise RuntimeError(f"Need at least {minimum_free // 1024**3}GB free SSD space for this installation stage.")
    tools = subprocess.run(['/usr/bin/xcode-select', '-p'], capture_output=True, text=True)
    if tools.returncode:
        raise RuntimeError("Install Apple Command Line Tools with xcode-select --install, complete the macOS dialogue, then rerun this installer.")
    for service, port in {**PORTS, "Captain": 4096, "conversation": 8003}.items():
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


def ensure_comfy_source(root):
    """Verify old installs and repair interrupted extraction without losing data."""
    directory = root / "ComfyUI"
    if directory.is_symlink():
        raise RuntimeError('ComfyUI source directory must not be a symlink')
    archive = root / "cache/ComfyUI.zip"
    download(f"https://github.com/Comfy-Org/ComfyUI/archive/{COMFY_COMMIT}.zip",
             archive, COMFY_SHA256)
    with tempfile.TemporaryDirectory(dir=root / "cache") as temporary:
        extract_zip(archive, temporary)
        sources = [p for p in Path(temporary).iterdir() if p.is_dir() and (p / "main.py").is_file()]
        if len(sources) != 1:
            raise RuntimeError("ComfyUI source archive layout has changed.")
        source = sources[0]
        if not directory.exists():
            source.rename(directory)
            return directory
        # Validate every existing upstream file before repairing missing ones.
        # Untracked models, outputs, workflows and custom nodes are untouched.
        missing = []
        for file in source.rglob('*'):
            relative = file.relative_to(source)
            target = directory / relative
            if any((directory / Path(*relative.parts[:i])).is_symlink()
                   for i in range(1, len(relative.parts) + 1)):
                raise RuntimeError('ComfyUI source contains a symlink: ' + str(relative))
            if file.is_dir():
                if target.exists() and not target.is_dir():
                    raise RuntimeError('ComfyUI source directory conflicts: ' + str(relative))
                continue
            if target.exists():
                if not target.is_file() or digest(target) != digest(file):
                    raise RuntimeError('ComfyUI source differs from pinned revision; preserved: ' + str(relative))
            else:
                missing.append((file, target))
        for file, target in missing:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Rename a fully written sibling so a crash never leaves half a
            # Python source file that later looks like a user modification.
            fd, name = tempfile.mkstemp(prefix='.local-ai-source-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(file.read_bytes())
                os.replace(name, target)
            finally:
                Path(name).unlink(missing_ok=True)
    return directory


def install_comfy(root, uv, state):
    directory = ensure_comfy_source(root)
    python = directory / ".venv/bin/python"
    environment_missing = not python.exists()
    if environment_missing:
        run([uv, "venv", "--python", "3.12", directory / ".venv"])
    deps_marker = directory / ".local-ai-dependencies.json"
    lock = SOURCE / 'locks/comfy-macos-arm64-py312.txt'
    required = {'comfy_commit': COMFY_COMMIT, 'torch': TORCH_VERSION,
                'torchvision': TORCHVISION_VERSION, 'torchaudio': TORCHAUDIO_VERSION,
                'lock_sha256': digest(lock)}
    try:
        installed_deps = json.loads(deps_marker.read_text())
    except (OSError, ValueError):
        installed_deps = None
    needs_dependencies = (environment_missing or
                          not completed(state, "comfy-dependencies") or
                          installed_deps != required)
    if needs_dependencies:
        # Resolve nothing at install time: all 85 transitive packages and
        # artifact hashes are locked for CPython 3.12 / macOS 15+ ARM64.
        run([uv, "pip", "install", "--python", python, '--require-hashes',
             '--only-binary', ':all:', '-r', lock])
    run([python, "-c", "import platform, torch, torchvision, torchaudio; "
         "assert platform.machine() == 'arm64'; "
         "assert (torch.__version__.split('+')[0], torchvision.__version__.split('+')[0], "
         "torchaudio.__version__.split('+')[0]) == ('2.10.0', '0.25.0', '2.10.0'); "
         "assert torch.backends.mps.is_available(), 'Apple GPU MPS is unavailable'; "
         "print('Pinned Apple GPU MPS: available')"])
    if needs_dependencies:
        # Mark success only AFTER all imports, exact versions and Metal MPS pass.
        # An upgrade will not reuse the old checkpoint with stale Torch.
        deps_marker.write_text(json.dumps(required, sort_keys=True) + "\n")
        checkpoint(state, "comfy-dependencies")
    return directory


def install_environments(root, uv, state, *, core=False):
    from feature_state import safe_path
    control = safe_path(root / "control")
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
    shutil.copytree(SOURCE / 'locks', control / 'locks', dirs_exist_ok=True)
    shutil.copytree(SOURCE / 'studio_sdk', control / 'studio_sdk', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(SOURCE / "web", control / "web", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Install only our descriptor-based save nodes; vault-mode CLI disables every
    # other external node. Keep the bundled copy in control for repair/checks.
    shutil.copytree(SOURCE / 'comfy_vault', control / 'comfy_vault',
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    python = control / ".venv/bin/python"
    if not python.exists():
        run([uv, "venv", "--python", "3.11", control / ".venv"])
    from dependency_locks import install_locked
    control_receipt = install_locked(uv, python, 'control', run)
    run([python, "-c", "import imageio_ffmpeg, subprocess; subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-version'], check=True)"])
    run([python, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=control)
    (control / '.local-ai-dependencies.json').write_text(json.dumps(control_receipt, sort_keys=True) + '\n')
    webui = root / "webui"
    (webui / "data").mkdir(parents=True, exist_ok=True)
    webui_missing = not (webui / ".venv/bin/python").exists()
    if webui_missing:
        run([uv, "venv", "--python", "3.11", webui / ".venv"])
    webui_python = webui / '.venv/bin/python'
    webui_receipt = install_locked(uv, webui_python, 'webui', run)
    run([webui_python, '-c', "import open_webui; from importlib.metadata import version; "
         f"assert version('open-webui') == '{WEBUI_RELEASE}'"])
    (webui / '.local-ai-dependencies.json').write_text(json.dumps(webui_receipt, sort_keys=True) + '\n')
    checkpoint(state, "webui-dependencies")
    from webui_local_images import harden, harden_pdf
    harden(root)
    harden_pdf(root)
    config_path = safe_path(control / "config.json")
    if not config_path.exists():
        config = {"comfy_dir": str(root / "ComfyUI"), "text_model": "qwen3:14b",
                  "thinking": True, "render_timeout_seconds": 3600,
                  "api_key": secrets.token_urlsafe(32), "webui_secret": secrets.token_urlsafe(48),
                  "ollama_url": "http://127.0.0.1:11435", "comfy_url": "http://127.0.0.1:8189",
                  "gateway_port": 8001, "public_url": "http://127.0.0.1:8001"}
        config_path.write_text(json.dumps(config, indent=2) + "\n")
        config_path.chmod(0o600)
    config = json.loads(config_path.read_text())
    upgraded = core_configuration(root, config) if core else full_configuration(config, root, uv)
    if upgraded != config:
        from feature_state import atomic_json
        backup = config_path.with_name("config.before-modular-install.json")
        if not backup.exists():
            atomic_json(backup, config)
        atomic_json(config_path, upgraded)
    return upgraded



def core_configuration(root, config):
    """Fresh core needs one pinned small fallback plus the shared Captain.

    Existing models, vault policies and optional settings retain their identity.
    A previous experimental trial backup is restored exactly once before migration.
    """
    import copy
    from feature_state import migrate, safe_path
    result = copy.deepcopy(config)
    if result.get('install_profile') == 'local-trial':
        backup = safe_path(root / 'control/trial-deferred-settings.json')
        if not backup.is_file():
            raise RuntimeError('Trial deferred settings are missing. Restore that private backup before migrating.')
        deferred = json.loads(backup.read_text())
        if not isinstance(deferred, dict) or not isinstance(deferred.get('text_models'), dict):
            raise RuntimeError('Trial deferred settings are incomplete; preserved for recovery.')
        for key, value in deferred.items():
            if key == 'text_models':
                # Retain the actual selected native Captain, restore other owner presets.
                result[key] = {**value, **result.get(key, {})}
            else:
                result[key] = value
    from model_team import preset
    from captain_config import upgrade as upgrade_captain
    if 'text_models' not in result:
        result['text_models'] = {'local-ai': preset('coordinator')}
        result['model_team_version'] = 1
        result['model_team'] = {'enabled': True, 'roles': {}}
        result['text_context_version'] = 2
        result['captain'] = {'enabled': False}
    result = upgrade_captain(upgrade_text_configuration(result))
    result['feature_schema'] = 1
    result['install_profile'] = 'core'
    migrate(root, result)
    return result


def full_configuration(config, root, uv):
    # Compatibility for callers of the previous Python API. User-facing full
    # installation uses the same modular feature functions as individual launchers.
    from captain_config import upgrade as upgrade_captain
    return upgrade_captain(upgrade_team(upgrade_text_configuration(config)))

def verify_text_cutoff(key, identifier, *, root=None):
    """Exercise native output exhaustion, not just a one-sentence smoke test."""
    response = http('http://127.0.0.1:8001/v1/chat/completions',
                    {'model': identifier, 'stream': False, 'max_completion_tokens': 8,
                     'messages': [{'role': 'user', 'content':
                                   'Write a detailed 2000-word essay about the history of computing.'}]},
                    key=key, timeout=4000)
    reason = response['choices'][0]['finish_reason']
    if root is not None:
        from native_diagnostics import diagnostic_path
        from feature_state import atomic_json
        atomic_json(diagnostic_path(root, 'cutoff-' + identifier), {
            'check': 'cutoff-' + identifier, 'model_id': identifier,
            'status': 'passed' if reason == 'length' else 'failed',
            'response': {key: response[key] for key in ('model', 'choices', 'usage') if key in response}})
    if reason != 'length':
        from turnkey_install import ReadinessError
        raise ReadinessError(f'{identifier}: output-cutoff acceptance did not report length')
    return {'finish_reason': reason, 'usage': response.get('usage', {})}


def verify_context_rejection(key, identifier, context):
    """Prove oversized inputs are rejected, including history and tool envelopes."""
    from turnkey_install import ReadinessError
    large = ' x' * max(context * 4, 4096)
    # At 32K context, the 4x fixture exceeds the separate 256 KiB tool
    # definition limit once JSON overhead is included. Keep this probe within
    # that envelope so it reaches the backend's context rejection check.
    schema_large = ' x' * max(context * 3, 4096)
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
            {'type': 'function', 'function': dict(tool['function'], description=schema_large)}]),
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
                raise ReadinessError(f'{identifier}/{name}: context acceptance returned an unexpected error (HTTP {error.code}); expected context_length_exceeded') from None
            results.append({'case': name, 'status': 'passed', 'code': 'context_length_exceeded'})
        else:
            raise ReadinessError(f'{identifier}/{name}: oversized input was accepted; native context protection is not verified')
    return results


def verify_generation(root, configuration, *, core=False):
    from feature_state import effective_config
    configuration = effective_config(root, configuration, testing=("core",) if core else ())
    import resource_modes
    if resource_modes.load(root / "control") != "max":
        raise RuntimeError("Native acceptance must run in Max mode; installer must select it temporarily.")
    processes = []
    gateway = None
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
        if not core:
            run([control / ".venv/bin/python", control / "check-workflows.py"], cwd=control)
        gateway = launch([control / ".venv/bin/python", control / "gateway.py"], control,
                         root / "logs/gateway.log", dict(os.environ, LOCAL_AI_ACCEPTANCE_FEATURES="core" if core else ""))
        processes.append(gateway)
        wait_ready("http://127.0.0.1:8001/health", gateway)
        webui = launch([root / "webui/.venv/bin/open-webui", "serve", "--host", "127.0.0.1", "--port", "8081"],
                       root / "webui", root / "logs/webui.log", webui_environment(root, configuration))
        processes.append(webui)
        wait_ready("http://127.0.0.1:8081/health", webui, timeout=600)
        ContextSettings().sync(http('http://127.0.0.1:8001/control/context', key=configuration['api_key']))
        checks = [("text-" + identifier, "Reply with one sentence about Python.", identifier)
                  for identifier in presets]
        checks.append(('text', 'Reply with one sentence about Python.', 'local-ai'))
        if not core:
            checks += [(kind, prompt, 'local-ai') for kind, prompt in (
                ('image', '/image A red toy car on a white table.'),
                ('text-after-image', 'Reply with one sentence about statistics.'),
                ('video', '/video A red toy car moves across a white table.'),
                ('text-after-video', 'Reply with one sentence about reproducibility.'))]
        report = {'tested_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'profile': 'core' if core else 'full', 'checks': [],
                  'media': 'not_run' if core else ('vault-direct' if configuration.get('vault', {}).get('enabled') else 'local')}
        if core:
            report['checks'].extend({'name': name, 'status': 'not_run',
                'reason': 'Run the independent feature installer for native acceptance.'}
                for name in ('image', 'video', 'speech', 'discord', 'vpn-web', 'remote-access'))
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
        if not core and configuration.get('speech', {}).get('enabled'):
            if (root / 'voice-engine/voices/default.json').exists():
                checks += [('speech', '/speak This is a local speech generation acceptance test.', 'local-ai-small'),
                           ('text-after-speech', 'Reply with one sentence about audio.', 'local-ai-small')]
            else:
                report['checks'].append({'name': 'speech-generation', 'status': 'not_run',
                    'reason': 'Base model loaded by voice installation, but no reference voice registered. Configure Voice.command, then rerun acceptance.'})
        for kind, prompt, identifier in checks:
            logging.info("Hardware acceptance test: %s. Video may take a long time.", kind)
            started = time.monotonic()
            from native_diagnostics import capture
            content, diagnostic = capture(root, kind, identifier, presets[identifier],
                lambda: http("http://127.0.0.1:8001/v1/chat/completions",
                             {"model": identifier, "stream": False,
                              "messages": [{"role": "user", "content": prompt}]},
                             key=configuration["api_key"], timeout=4000), prompt=prompt,
                residency=(lambda: verify_text_residency(configuration, presets, identifier))
                          if kind.startswith('text') else None)
            if kind in {"image", "video", "speech"}:
                extension = '.wav' if kind == 'speech' else ".png" if kind == "image" else ".mp4"
                if extension not in content:
                    raise RuntimeError(f"{kind} did not return the expected saved output.")
                verify_text_residency(configuration, presets, None)
                if port_open(PORTS["comfy"]):
                    raise RuntimeError("ComfyUI remained running after its visual job.")
            report["checks"].append({"name": kind, "model_id": identifier,
                                     "seconds": round(time.monotonic() - started, 1),
                                     "status": "passed", "result": content, 'diagnostic': str(diagnostic)})
            (root / "acceptance-report.json").write_text(json.dumps(report, indent=2) + "\n")
            if kind == 'text-' + identifier:
                cutoff = verify_text_cutoff(configuration['api_key'], identifier, root=root)
                report['checks'].append({'name': 'cutoff-' + identifier, 'model_id': identifier,
                                         'status': 'passed', **cutoff})
                context_checks = verify_context_rejection(configuration['api_key'], identifier, presets[identifier]['num_ctx'])
                report['checks'].append({'name': 'context-' + identifier, 'model_id': identifier,
                                         'status': 'passed', 'cases': context_checks})
            (root / "acceptance-report.json").write_text(json.dumps(report, indent=2) + "\n")
        from team_setup import verify_native_handoffs
        logging.info('Hardware acceptance test: OpenCode specialist handoffs')
        report['checks'].extend(verify_native_handoffs(root, configuration))
        from captain_check import verify as verify_captain
        logging.info('Hardware acceptance test: Captain dispatch and retirement')
        report['checks'].extend(verify_captain(root, configuration))
        (root / "acceptance-report.json").write_text(json.dumps(report, indent=2) + "\n")
    finally:
        for process in reversed(processes):
            stop_process(process, timeout=4200, cooperative=process is gateway)


def verify_text_residency(configuration, presets, identifier):
    """Acceptance observes every owned text backend, not just primary Ollama."""
    captain = configuration.get('captain', {})
    from turnkey_install import ReadinessError
    observed = {}
    shared = captain.get('enabled') and identifier == captain.get('model_id')
    native = shared and captain.get('provider') == 'llama'
    bases = [('primary', 'http://127.0.0.1:11435')]
    if captain.get('enabled') and captain.get('provider', 'ollama') == 'ollama':
        bases.append(('shared', 'http://127.0.0.1:11436'))
    owner = 'shared' if shared else 'primary'
    for name, base in bases:
        loaded = http(base + '/api/ps').get('models', [])
        observed[name] = [model['name'] for model in loaded]
        expected = presets[identifier]['model'] if identifier and not native and owner == name else None
        if any(model['name'] != expected for model in loaded):
            raise ReadinessError('Unexpected resident text model on ' + name + ' after a model/media handoff')
    if captain.get('enabled') and captain.get('provider') == 'llama':
        if port_open(PORTS['shared_gguf']) != bool(native):
            raise ReadinessError('Shared GGUF residency did not match the completed model/media handoff')
        observed['shared_gguf_listening'] = bool(native)
    return observed


def verify_generation_during_install(root, configuration, *, core=False):
    """Installer-owned Max acceptance without permanent changes to owner modes.

    Preconditions: installer lock held, preflight confirmed all app ports free.
    This must not be called against a running service.
    """
    import resource_modes
    control = root / "control"
    saved_mode = resource_modes.load(control)
    if saved_mode != "max":
        resource_modes.save(control, "max")
    try:
        if core:
            verify_generation(root, configuration, core=True)
        else:
            verify_generation(root, configuration)
    finally:
        if saved_mode != "max":
            resource_modes.save(control, saved_mode)


def make_launcher(root):
    command = root / "Start Local AI.command"
    launch_script = ("#!/bin/bash\nset -e\ncd " + shlex.quote(str(root / "control")) +
                     "\nexec .venv/bin/python turnkey_install.py --root " + shlex.quote(str(root)) + "\n")
    command.write_text(launch_script)
    command.chmod(0o755)
    captain_launcher = root / 'Open Captain.command'
    captain_launcher.write_text(launch_script)
    captain_launcher.chmod(0o755)
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
    village_helper = root / 'Agent Village.command'
    village_helper.write_text('#!/bin/bash\nset -e\ncd ' + shlex.quote(str(root / 'control')) +
                              '\nexec .venv/bin/python village.py --root ' +
                              shlex.quote(str(root / 'village')) + ' "$@"\n')
    village_helper.chmod(0o755)
    for label,operation in (('Back Up Village','backup'),('Restore Village','restore'),('Forget Village Source','forget')):
        helper=root/(label+'.command')
        helper.write_text('#!/bin/bash\nset -e\ncd '+shlex.quote(str(root/'control'))+'\nexec .venv/bin/python village_owner.py --root '+shlex.quote(str(root))+' --operation '+operation+' \"$@\"\n')
        helper.chmod(0o755)
    commons_helper=root/'Village Commons.command'
    commons_helper.write_text('#!/bin/bash\nset -e\ncd '+shlex.quote(str(root/'control'))+
        '\nexec .venv/bin/python commons_control.py --root '+shlex.quote(str(root))+' "$@"\n')
    commons_helper.chmod(0o755)
    studio_helper=root/'Village Institutions.command'
    studio_helper.write_text('#!/bin/bash\nset -e\ncd '+shlex.quote(str(root/'control'))+
        '\nexec .venv/bin/python studio_control.py --root '+shlex.quote(str(root))+' "$@"\n')
    studio_helper.chmod(0o755)
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
    parser.add_argument('--root', type=Path, default=Path.home() / 'LocalAI-Automated')
    parser.add_argument('--uv', type=Path, required=True)
    parser.add_argument('--everything', action='store_true', help='Core plus the independent feature installers.')
    parser.add_argument('--minicpm-captain', action='store_true', help='Compatibility: core always includes MiniCPM.')
    parser.add_argument('--local-trial', action='store_true', help='Compatibility alias for the stable core profile.')
    parser.add_argument('--defer-discord', action='store_true', help='Skip Discord during Install Everything.')
    parser.add_argument('--web-access', action='store_true')
    parser.add_argument('--remote-access', action='store_true')
    args = parser.parse_args()
    if args.local_trial and args.everything:
        parser.error('--local-trial and --everything cannot be combined')
    from feature_state import (atomic_json, effective_config, installation_lock, read,
                               safe_path, snapshot, write)
    root = safe_path(args.root.expanduser()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in ('logs', 'cache', 'tools', 'models/ollama'):
        safe_path(root / name).mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(root / 'logs/install.log')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler(), file_handler])
    state = root / 'install-state.json'
    started = False
    try:
        with installation_lock(root):
            from feature_install import ensure_stopped, make_launchers, run_feature, INSTALLERS
            ensure_stopped(root)
            logging.info('Core: Apple Silicon, developer tools, free space and port checks')
            try:
                preflight(root, core=True)
            except RuntimeError as error:
                print(str(error))
                raise
            write(root, 'core', 'installed', next_action='Rerun Install LOCAL AI Core.command', acceptance={})
            started = True
            install_ollama(root)
            checkpoint(state, 'ollama-installed')
            configuration = install_environments(root, args.uv, state, core=True)
            from work_agent import install as install_work_agent
            install_work_agent(root, download, run)
            from captain_setup import install_minicpm
            configuration = install_minicpm(root, download)
            write(root, 'core', 'testing')
            # Core acceptance is independent of optional state and never prompts
            # for its inputs. Keep its fingerprint separate from feature checks.
            fingerprint = acceptance_fingerprint(root)
            accepted_file = root / 'accepted-core-fingerprint.txt'
            if not accepted_file.exists() or accepted_file.read_text() != fingerprint:
                verify_generation_during_install(root, configuration, core=True)
                accepted_file.write_text(fingerprint)
            from turnkey_install import acceptance_summary
            native = acceptance_summary(root, configuration)
            import resource_modes
            if not (root / 'control/resource-mode.json').exists():
                resource_modes.save(root / 'control', 'normal')
            application = make_launcher(root)
            make_launchers(root)
            for directory in (root / 'control', root / 'webui'):
                with (directory / 'installed-versions.txt').open('w') as output:
                    run([args.uv, 'pip', 'freeze', '--python', directory / '.venv/bin/python'], stdout=output)
            atomic_json(root / 'software-versions.json', {
                'open_webui': WEBUI_RELEASE, 'opencode': '1.18.34',
                'text_models': configured_text_models(configuration)})
            # Prove the same authenticated UI and MCP policy used in daily operation
            # before advertising core readiness or installing dependent features.
            from feature_checks import services
            from turnkey_install import await_background
            with services(root, ('core',), captain=True) as test_config:
                await_background(root, test_config, require_integrations=False)
            write(root, 'core', 'ready', acceptance=native, installed_version='modular-core-v1',
                  validated_hashes={'acceptance_fingerprint': fingerprint}, last_failure=None, next_action='')
            selected = list(INSTALLERS) if args.everything else []
            if args.web_access and 'web' not in selected:
                selected.append('web')
            if args.remote_access and 'remote' not in selected:
                selected.append('remote')
            if args.defer_discord and 'discord' in selected:
                selected.remove('discord')
            for feature in selected:
                run_feature(root, feature, args.uv)
            configuration = json.loads((root / 'control/config.json').read_text())
        # Runtime takes the shared installation lock. It can start only after
        # source/config mutations finish and the exclusive lock is released.
        from turnkey_install import start_login_service, await_background, write_receipt, open_local_ui
        start_login_service(root)
        live_config = effective_config(root, configuration)
        background = await_background(root, live_config, require_integrations=False)
        receipt = write_receipt(root, configuration, native, background, require_integrations=False)
        with installation_lock(root, shared=True):
            write(root, 'core', 'ready', acceptance={**native, 'background_services': background},
                  last_failure=None, next_action='', pending_checks=receipt['pending_physical_acceptance'])
            checkpoint(state, 'installed')
        logging.info('Core ready. Daily launcher: %s', application)
        print('Captain ready at http://127.0.0.1:4096. Starts after macOS login.')
        print('Run Check LOCAL AI Setup.command for optional features and checks not yet run.')
        open_local_ui(root)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # Never log credentials/requests from third-party exceptions.
        logging.error('Core installation stopped (%s). Completed files are preserved.', type(error).__name__)
        from turnkey_install import ReadinessError
        if isinstance(error, ReadinessError):
            logging.error('%s', error)
        print('Installation stopped. Run the same installer to resume. Check logs/install.log.')
        # Lock conflicts must not change a receipt belonging to another installer.
        try:
            if not started:
                return 1
            with installation_lock(root, shared=True):
                write(root, 'core', 'failed', last_failure=type(error).__name__,
                      next_action='Rerun Install LOCAL AI Core.command. Completed files are preserved.')
        except RuntimeError:
            pass
        return 1
    finally:
        logging.getLogger().removeHandler(file_handler)
        file_handler.close()


if __name__ == '__main__':
    sys.exit(main())
