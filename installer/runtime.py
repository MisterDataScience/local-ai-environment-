"""Foreground supervisor: starts local services, opens Safari and cleans up."""
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import time

from common import PORTS, http, launch, ollama_binary, ollama_environment, port_open, stop_process, wait_ready, webui_environment


def main():
    root = Path(__file__).resolve().parent.parent
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock = (root / ".runtime.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Local AI is already running. Open http://127.0.0.1:8081 in Safari.")
    config = json.loads((root / "control/config.json").read_text())
    processes = []
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        for service, port in PORTS.items():
            if port_open(port):
                raise RuntimeError(f"{service} port {port} is already occupied. No existing process was stopped.")
        ollama = launch([ollama_binary(root), "serve"], root, root / "logs/ollama.log", ollama_environment(root))
        processes.append(("ollama", ollama))
        wait_ready("http://127.0.0.1:11435/api/version", ollama)
        gateway = launch([root / "control/.venv/bin/python", root / "control/gateway.py"],
                         root / "control", root / "logs/gateway.log", os.environ.copy())
        processes.append(("gateway", gateway))
        wait_ready("http://127.0.0.1:8001/health", gateway)
        webui = launch([root / "webui/.venv/bin/open-webui", "serve", "--host", "127.0.0.1", "--port", "8081"],
                       root / "webui", root / "logs/webui.log", webui_environment(root, config))
        processes.append(("webui", webui))
        wait_ready("http://127.0.0.1:8081/health", webui, timeout=600)
        # Verify the gateway model list is available before presenting the chat UI.
        models = http("http://127.0.0.1:8001/v1/models", key=config["api_key"])
        if not any(model["id"] == "local-ai" for model in models["data"]):
            raise RuntimeError("The local-ai gateway model is unavailable.")
        subprocess.run(["/usr/bin/open", "-a", "Safari", "http://127.0.0.1:8081"], check=True)
        print("\nLocal AI is running at http://127.0.0.1:8081")
        print("Select Everyday, Small or Large in the chat's model menu. Models load on a request.")
        print("These are text presets, not Gaming Mode. Media remains available with each preset.")
        print("Use ordinary text, /image DESCRIPTION, or /video DESCRIPTION.")
        print("Leave this Terminal open. Press Control+C here to shut down.")
        while True:
            for name, process in processes:
                if process.poll() is not None:
                    raise RuntimeError(f"{name} exited. Read {root / 'logs' / (name + '.log')}")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nShutting down. An active generation will finish or time out before memory is released.")
    except Exception as error:
        logging.exception("Local AI stopped: %s", error)
        return 1
    finally:
        # Ignore repeat interrupts while the gateway performs its renderer cleanup.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        for name, process in reversed(processes):
            stop_process(process, timeout=4200 if name == "gateway" else 90)
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
