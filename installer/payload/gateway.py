"""Loopback gateway entry point: process lock, listeners and shutdown."""

import fcntl
from http.server import ThreadingHTTPServer
import json
import logging
from pathlib import Path
import signal
import threading
from urllib.parse import urlparse

from backend_http import port_open
from http_api import Handler, MediaHandler
from model_engine import Engine

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("gateway")


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
        server.server_close()
        server.engine.executor.shutdown(wait=True)
        server.engine.stop_comfy()
        if media_server:
            media_server.shutdown()
            media_server.server_close()
        lock_file.close()


if __name__ == "__main__":
    main()
