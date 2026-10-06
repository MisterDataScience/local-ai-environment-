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
    remote = config.get("remote_access", {})
    if remote.get("enabled"):
        from remote_access import cli_json, assert_private_ports
        # Refuse to activate the local service behind an existing public Funnel route.
        try:
            assert_private_ports(cli_json("serve", "status", "--json"), remote["hostname"])
        except subprocess.SubprocessError:
            logging.warning("Tailscale status is unavailable. Remote access may be offline.")
    processes = []
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        for service, port in PORTS.items():
            if port_open(port):
                raise RuntimeError(f"{service} port {port} is already occupied. No existing process was stopped.")
        if config.get("web", {}).get("enabled"):
            from web_access import start as start_web
            try:
                start_web(root)
            except Exception:
                logging.warning("VPN web service unavailable. Local AI will continue without web access.")
        if config.get('vault', {}).get('enabled'):
            from vault_backup import snapshot
            try:
                saved = snapshot(root, config)
                if saved:
                    logging.info('Pre-start encrypted backup saved: %s', saved)
            except Exception:
                logging.warning('Encrypted backup unavailable. Unlock the vault and use Back Up AI Workspace after stopping Local AI.')
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
        if not models["data"]:
            raise RuntimeError("The local-ai gateway model is unavailable.")
        if remote.get("enabled"):
            from remote_access import verify_remote_access
            try:
                verify_remote_access(root, remote)
                logging.info("Private HTTPS chat and media checks passed. Test another device next.")
            except Exception as error:
                logging.warning("Remote checks did not pass: %s. Local chat is still running.", error)
                from remote_access import atomic_json
                atomic_json(root / "remote-acceptance-report.json",
                            {"status": "failed", "error": str(error), "other_device_browser_test": "pending"})
        subprocess.run(["/usr/bin/open", "-a", "Safari", "http://127.0.0.1:8081"], check=True)
        print("\nLocal AI is running at http://127.0.0.1:8081")
        if remote.get("enabled"):
            print("Private remote chat:", remote["ui_url"])
            print("Connect Tailscale on your other devices, then open that address.")
        print("Select Everyday, Small or Large in the chat's model menu. Models load on a request.")
        print("Open AI Modes.command to choose Gaming, Normal or Max. This applies to all devices.")
        if config.get('vault', {}).get('enabled'):
            from vault_tools import mounted_root
            try:
                with mounted_root(config):
                    print('Encrypted AI Workspace is unlocked.')
            except (OSError, RuntimeError, ValueError):
                print('Unlock AI Workspace in Cryptomator on the Mac to use file tools.')
            print('Vault media saves to Outputs/Media. Local chat data is backed up to the vault on clean shutdown.')
        else:
            print("Use ordinary text, /image DESCRIPTION, or /video DESCRIPTION.")
        if config.get("web", {}).get("enabled"):
            print("Web: /search QUERY or /read https://example.org QUESTION. VPN required; no fallback.")
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
        if config.get('vault', {}).get('enabled'):
            from vault_backup import snapshot
            try:
                saved = snapshot(root, config)
                if saved:
                    logging.info('Encrypted shutdown backup saved: %s', saved)
            except Exception:
                logging.warning('Backup not completed. Unlock the vault and run Back Up AI Workspace.command while Local AI is stopped.')
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
