"""Loopback gateway entry point: process lock, listeners and shutdown."""

import fcntl
from http.server import ThreadingHTTPServer
import json
import logging
from pathlib import Path
import signal
import threading
from urllib.parse import urlparse

from backend_http import port_open, api
from context_policy import require_backend_version
from http_api import Handler, MediaHandler
from model_engine import Engine

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("gateway")


def cleanup(engine, server, media_server, lock_file):
    """Attempt every owned cleanup even if an earlier backend refuses release."""
    operations = [('audio', lambda: engine.audio.control('stop')),
                  ('listener', server.server_close),
                  ('inference queue', lambda: engine.executor.shutdown(wait=True)),
                  ('media model', engine.stop_comfy)]
    if engine.__dict__.get('commons') is not None:
        operations.insert(0, ('commons', engine.commons.shutdown))
    if engine.shared_llama:
        operations.append(('shared model', engine.shared_llama.stop))
    if media_server:
        operations.extend([('media listener', media_server.shutdown), ('media socket', media_server.server_close)])
    operations.append(('process lock', lock_file.close))
    failures = []
    for name, operation in operations:
        try:
            operation()
        except Exception:
            failures.append(name)
            LOG.error('Gateway cleanup failed for %s; continuing remaining cleanup', name)
    if failures:
        raise RuntimeError('Gateway could not confirm release of: ' + ', '.join(failures))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock_file = (ROOT / ".gateway.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another copy of this gateway is already running.")
    config = json.loads((ROOT / "config.json").read_text())
    try:
        require_backend_version(api(config.get('ollama_url', 'http://127.0.0.1:11434'), '/api/version').get('version'))
    except Exception:
        lock_file.close()
        raise
    if port_open(urlparse(config.get("comfy_url", "http://127.0.0.1:8188")).port):
        raise SystemExit("Stop manually started ComfyUI before starting the gateway.")
    server = ThreadingHTTPServer(("127.0.0.1", config.get("gateway_port", 8000)), Handler)
    server.daemon_threads = True
    server.engine = Engine(config)
    server.engine.change_mode(server.engine.mode)  # Release any leftover weights before admitting work.
    stopping = threading.Event()
    def expire_audio():
        while not stopping.wait(5):
            server.engine.audio.expire()
            try:
                server.engine.expire_shared()
            except (RuntimeError, OSError):
                LOG.warning('Shared model idle release failed; model handoffs still require verified release.')
    threading.Thread(target=expire_audio, daemon=True).start()
    media_server = None
    if config.get("remote_access", {}).get("enabled"):
        try:
            media_server = ThreadingHTTPServer(("127.0.0.1", 8002), MediaHandler)
            media_server.daemon_threads = True
            media_server.engine = server.engine
            threading.Thread(target=media_server.serve_forever, daemon=True).start()
        except BaseException:
            server.server_close()
            server.engine.executor.shutdown(wait=True)
            raise
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
        stopping.set()
        cleanup(server.engine, server, media_server, lock_file)


if __name__ == "__main__":
    main()

