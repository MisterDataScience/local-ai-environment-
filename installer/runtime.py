"""Foreground supervisor: starts local services, opens Safari and cleans up."""
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import time
import argparse
import threading

from common import PORTS, http, launch, ollama_binary, ollama_environment, port_open, stop_process, wait_ready, webui_environment
from context_settings import ContextSettings


def main(background=False):
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
    from discord_runtime import DiscordSupervisor
    discord = DiscordSupervisor(root, config)
    processes = []
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        from service_lifecycle import recover, record, publish_runtime
        recover(root)
        publish_runtime(root)
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
        record(root, processes)
        wait_ready("http://127.0.0.1:11435/api/version", ollama)
        if config.get('captain', {}).get('enabled') and config['captain'].get('provider', 'ollama') == 'ollama':
            shared = launch([ollama_binary(root), 'serve'], root, root / 'logs/shared-text.log',
                            ollama_environment(root, parallel=config['captain']['max_parallel'], port=11436))
            processes.append(('shared_text', shared))
            record(root, processes)
            wait_ready('http://127.0.0.1:11436/api/version', shared)
        gateway = launch([root / "control/.venv/bin/python", root / "control/gateway.py"],
                         root / "control", root / "logs/gateway.log", os.environ.copy())
        processes.append(("gateway", gateway))
        record(root, processes)
        wait_ready("http://127.0.0.1:8001/health", gateway)
        from webui_local_images import harden, harden_pdf
        harden(root)
        harden_pdf(root)
        webui = launch([root / "webui/.venv/bin/open-webui", "serve", "--host", "127.0.0.1", "--port", "8081"],
                       root / "webui", root / "logs/webui.log", webui_environment(root, config))
        processes.append(("webui", webui))
        record(root, processes)
        wait_ready("http://127.0.0.1:8081/health", webui, timeout=600)
        # Verify the gateway model list is available before presenting the chat UI.
        models = http("http://127.0.0.1:8001/v1/models", key=config["api_key"])
        if not models["data"]:
            raise RuntimeError("The local-ai gateway model is unavailable.")
        from managed_captain import wait_for_agent
        captain_retry = 0
        def launch_captain():
            if port_open(4096):
                raise RuntimeError('Captain UI port 4096 already occupied')
            process = launch([root / 'control/.venv/bin/python', root / 'control/work_agent.py',
                              '--root', root, '--managed'],
                             root / 'control', root / 'logs/captain.log', os.environ.copy())
            processes.append(('captain', process))
            record(root, processes)
            wait_for_agent(root, process)
            logging.info('Native Captain Work Agent is connected and ready at http://127.0.0.1:4096')
        if config.get('captain', {}).get('enabled'):
            from payload import resource_modes
            if resource_modes.load(root / 'control') in {'normal', 'max'}:
                launch_captain()
        context_settings = ContextSettings()
        context_warning = False
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
        if not background:
            address = 'http://127.0.0.1:4096' if any(name == 'captain' for name, _ in processes) else 'http://127.0.0.1:8081'
            subprocess.run(["/usr/bin/open", "-a", "Safari", address], check=True)
        from attachment_setup import configure as configure_attachments
        configure_attachments(root)
        print("\nLocal AI is running at http://127.0.0.1:8081")
        if config.get('captain', {}).get('enabled'):
            print('Captain Work Agent: http://127.0.0.1:4096 (private credentials in control/captain-ui-auth.json)')
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
        if config.get("browser", {}).get("enabled"):
            print("Browser: Playwright MCP over Proton VPN. Enable its integration in chat.")
        if config.get("web", {}).get("enabled"):
            print("Web: /search QUERY or /read https://example.org QUESTION. VPN required; no fallback.")
        print('Background operation active.' if background else 'Press Control+C here to shut down.')
        health_failures = 0
        last_tick = time.monotonic()
        retry_web = 0
        web_thread = None
        def recover_web():
            try:
                from web_access import status, start
                if status(root).get('status') != 'ready':
                    start(root)
            except Exception:
                logging.warning('VPN service unavailable; web access remains blocked.')
        while True:
            for name, process in list(processes):
                if process.poll() is not None:
                    if name == 'captain':
                        processes.remove((name, process))
                        record(root, processes)
                        logging.warning('Captain exited; it will restart when the gateway is ready.')
                    else:
                        raise RuntimeError(f"{name} exited. Read {root / 'logs' / (name + '.log')}")
            now = time.monotonic()
            # After sleep, allow readiness to settle before restarting anything.
            if now - last_tick > 30:
                health_failures = 0
                logging.info('Resuming service readiness checks after suspension.')
            last_tick = now
            if config.get('captain', {}).get('enabled') and not any(name == 'captain' for name, _ in processes) and now >= captain_retry:
                captain_retry = now + 30
                try:
                    mode = http('http://127.0.0.1:8001/control/mode', key=config['api_key'], timeout=3)
                    if mode['mode'] in {'normal', 'max'} and not mode['transitioning'] and not mode['error']:
                        launch_captain()
                except Exception as error:
                    logging.warning('Managed Captain waiting for restart: %s', error)
            if config.get('web', {}).get('enabled') and now >= retry_web and (web_thread is None or not web_thread.is_alive()):
                web_thread = threading.Thread(target=recover_web, daemon=True)
                web_thread.start()
                retry_web = now + 60
            try:
                http('http://127.0.0.1:11435/api/version', timeout=3)
                http('http://127.0.0.1:8081/health', timeout=3)
                health_failures = 0
            except Exception:
                health_failures += 1
                if health_failures >= 10:
                    raise RuntimeError('Local service remained unresponsive; background LaunchAgent will restart after cleanup.')
            try:
                policy = http('http://127.0.0.1:8001/control/context', key=config['api_key'], timeout=2)
                if context_settings.sync(policy):
                    logging.info('Native context compaction set for %s: %s tokens', policy['mode'], policy['threshold'])
                context_warning = False
            except Exception:
                if not context_warning:
                    logging.warning('Context settings could not be refreshed; retrying. Oversized requests must still fail at the backend.')
                context_warning = True
            try:
                discord.tick(http('http://127.0.0.1:8001/control/mode', key=config['api_key'], timeout=3))
            except Exception:
                discord.stop()
                logging.warning('Discord waiting for the gateway.')
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
        discord.stop()
        for name, process in reversed(processes):
            stop_process(process, timeout=4200 if name == "gateway" else 90)
        if processes:
            (root / 'control/runtime-services.json').unlink(missing_ok=True)
        (root / 'control/runtime-owner.json').unlink(missing_ok=True)
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--background', action='store_true')
    raise SystemExit(main(parser.parse_args().background))


