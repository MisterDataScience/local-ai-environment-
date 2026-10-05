"""Shared local service configuration and process lifecycle helpers."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

PORTS = {"ollama": 11435, "gateway": 8001, "comfy": 8189, "webui": 8081}


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def http(url, payload=None, key=None, timeout=30):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    data = None if payload is None else json.dumps(payload).encode()
    with urlopen(Request(url, data=data, headers=headers), timeout=timeout) as response:
        return json.load(response)


def wait_ready(url, process, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Service exited before becoming ready: {url}")
        try:
            http(url, timeout=2)
            return
        except (URLError, TimeoutError, OSError):
            time.sleep(1)
    raise RuntimeError(f"Service did not become ready within {timeout} seconds: {url}")


def stop_process(process, timeout=90):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # The gateway may be releasing a renderer. Allow graceful cleanup first.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=15)


def launch(command, cwd, log_path, environment):
    with Path(log_path).open("ab") as log:
        return subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                env=environment, start_new_session=True)


def ollama_environment(root):
    env = os.environ.copy()
    env.update({"OLLAMA_HOST": f"127.0.0.1:{PORTS['ollama']}",
                "OLLAMA_MODELS": str(root / "models/ollama"),
                "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1",
                "OLLAMA_CONTEXT_LENGTH": "8192", "OLLAMA_KEEP_ALIVE": "5m",
                "OLLAMA_NO_CLOUD": "1"})
    return env


def webui_environment(root, configuration):
    env = os.environ.copy()
    env.update({
        "DATA_DIR": str(root / "webui/data"), "WEBUI_AUTH": "False",
        "WEBUI_SECRET_KEY": configuration["webui_secret"],
        "ENABLE_PERSISTENT_CONFIG": "False", "ENABLE_OLLAMA_API": "False",
        "ENABLE_OPENAI_API": "True", "OPENAI_API_BASE_URL": "http://127.0.0.1:8001/v1",
        "OPENAI_API_BASE_URLS": "http://127.0.0.1:8001/v1",
        "OPENAI_API_KEY": configuration["api_key"],
        "OPENAI_API_KEYS": configuration["api_key"], "DEFAULT_MODELS": "local-ai",
        "ENABLE_TITLE_GENERATION": "False", "ENABLE_TAGS_GENERATION": "False",
        "ENABLE_FOLLOW_UP_GENERATION": "False", "ENABLE_IMAGE_GENERATION": "False",
        "ENABLE_IMAGE_PROMPT_GENERATION": "False", "ENABLE_COMMUNITY_SHARING": "False",
        "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "true",
        "CUDA_VISIBLE_DEVICES": "", "RAG_EMBEDDING_MODEL_DEVICE": "cpu",
        "WHISPER_MODEL_DEVICE": "cpu",
    })
    return env


def ollama_binary(root):
    return root / "tools/Ollama.app/Contents/Resources/ollama"
