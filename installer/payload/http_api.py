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
from web_tools_api import specification, execute as retrieve_tool
import vault_tools
import vault_media
import resource_modes
from backend_http import completion_error

LOG = logging.getLogger("gateway")


def completion_message(result):
    message = {"role": "assistant", "content": result} if isinstance(result, str) else result
    return message, "tool_calls" if message.get("tool_calls") else "stop"


def completion_delta(message):
    delta = dict(message)
    if message.get("tool_calls"):
        delta["tool_calls"] = [dict(call, index=i) for i, call in enumerate(message["tool_calls"])]
    return delta


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

    def vault_media_response(self, name):
        from pathlib import Path
        headers_sent = False
        try:
            with vault_media.open_media(self.server.engine.config, name) as (source, size, root_fd):
                types = {'.png': 'image/png', '.webp': 'image/webp', '.mp4': 'video/mp4', '.webm': 'video/webm'}
                # Range requests are needed by mobile video players.
                start, end, code = 0, size - 1, 200
                requested = self.headers.get('Range')
                if requested:
                    import re
                    match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                    if not match or not any(match.groups()):
                        return self.json_response(416, {'error': 'Unsupported byte range'})
                    left, right = match.groups()
                    if left:
                        start = int(left)
                        end = min(int(right), end) if right else end
                    else:
                        start = max(0, size - int(right))
                    if start > end or start >= size:
                        return self.json_response(416, {'error': 'Range outside file'})
                    code = 206
                vault_media.same_mount(self.server.engine.config, root_fd)
                self.send_response(code)
                self.send_header('Content-Type', types[Path(name).suffix])
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Accept-Ranges', 'bytes')
                if code == 206:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                headers_sent = True
                source.seek(start)
                remaining = end - start + 1
                while remaining:
                    vault_media.same_mount(self.server.engine.config, root_fd)
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise OSError('Media ended unexpectedly')
                    self.wfile.write(block)
                    remaining -= len(block)
        except (ValueError, RuntimeError, OSError):
            if headers_sent:
                self.close_connection = True
            else:
                return self.json_response(409, {'error': 'Unlock the configured vault on the Mac; media is unavailable.'})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/modes':
            content = resource_modes.PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/health":
            return self.json_response(503 if self.server.engine.mode_transitioning or self.server.engine.mode_error else 200, {"status": "switching" if self.server.engine.mode_transitioning else "blocked" if self.server.engine.mode_error else "ok", "state": self.server.engine.state})
        if path.startswith("/media/"):
            if self.server.engine.config.get('vault', {}).get('enabled'):
                return self.vault_media_response(path.removeprefix('/media/'))
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
        if path == "/control/mode":
            return self.json_response(200, self.server.engine.mode_status())
        if path == "/v1/models":
            return self.json_response(200, {"object": "list", "data": [
                {"id": identifier, "name": preset["name"], "object": "model", "created": 0,
                 "owned_by": "local"} for identifier, preset in self.server.engine.visible_models().items()]})
        if path == "/workspace/openapi.json":
            return self.json_response(200, vault_tools.specification())
        if path == "/tools/openapi.json":
            return self.json_response(200, specification())
        self.json_response(404, {"error": "Not found"})

    def do_POST(self):
        if not self.authorised():
            return
        path = urlparse(self.path).path
        if path == '/control/mode':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 256:
                    self.close_connection = True
                    raise ValueError('Invalid mode request size')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or set(body) != {'mode'} or not isinstance(body['mode'], str):
                    raise ValueError('Expected a mode name only')
                return self.json_response(202, self.server.engine.change_mode(body['mode']))
            except (ValueError, RuntimeError, OSError) as error:
                return self.json_response(409, {'error': str(error)})
        if path.startswith('/workspace/'):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1600000:
                    self.close_connection = True
                    raise ValueError('Invalid workspace request size')
                body = json.loads(self.rfile.read(length))
                result = vault_tools.execute(self.server.engine.config, path.rsplit('/', 1)[1], body)
                return self.json_response(200, result)
            except (ValueError, RuntimeError, OSError) as error:
                return self.json_response(409, {'error': str(error)})
        if path in {"/tools/vpn_search_web", "/tools/vpn_read_page", "/tools/vpn_reverse_image"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("Invalid retrieval request size")
                body = json.loads(self.rfile.read(length))
                return self.json_response(200, retrieve_tool(self.server.engine.config, path.rsplit("/", 1)[1], body))
            except (ValueError, RuntimeError) as error:
                return self.json_response(400, {"error": str(error)})
        if path != "/v1/chat/completions":
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
                message, finish = completion_message(content)
                return self.json_response(200, {"id": identifier, "object": "chat.completion",
                    "created": created, "model": body["model"], "usage": body.get("_usage", {}), "choices": [
                        {"index": 0, "message": message, "finish_reason": finish}]})
            except Exception as error:
                LOG.exception("Request failed")
                status, payload = completion_error(error)
                return self.json_response(status, payload)
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
                # Headers have already been sent. Emit an error event, never a
                # successful assistant turn containing the error text.
                _, payload = completion_error(error)
                self.wfile.write(("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode())
                self.wfile.flush()
                return
            message, reason = completion_message(content)
            for delta, finish in [(completion_delta(message), None), ({}, reason)]:
                chunk = {"id": identifier, "object": "chat.completion.chunk", "created": created,
                         "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                if finish and body.get("_usage"):
                    chunk["usage"] = body["_usage"]
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
