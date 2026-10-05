"""Authenticated OpenAI-compatible HTTP API and isolated media-only handler."""

import concurrent.futures
from http.server import BaseHTTPRequestHandler
import json
import logging
import secrets
import shutil
import time
from urllib.parse import urlparse
import uuid

LOG = logging.getLogger("gateway")


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


class MediaHandler(Handler):
    """Separate loopback listener exposing generated files only, never the model API."""
    def do_GET(self):
        if not urlparse(self.path).path.startswith("/media/"):
            return self.json_response(404, {"error": "Not found"})
        return super().do_GET()

    def do_POST(self):
        self.close_connection = True
        return self.json_response(404, {"error": "Not found"})
