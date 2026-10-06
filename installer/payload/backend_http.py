"""JSON calls to local backends and loopback port checks."""

import json
import socket
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class ContextLengthError(RuntimeError):
    """An explicit backend context rejection, not an estimated token count."""


def completion_error(error):
    if isinstance(error, ContextLengthError):
        return 400, {"error": {"message": "Context length exceeded. Compact the conversation or reduce the supplied content.",
                               "type": "invalid_request_error", "code": "context_length_exceeded"}}
    return 502, {"error": {"message": str(error), "type": "server_error", "code": "backend_error"}}


def api(base, path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read(8192).decode(errors="replace")
        try:
            value = json.loads(detail)
            message = value.get("error", "") if isinstance(value, dict) else ""
            if isinstance(message, dict):
                message = message.get("message", "")
            explicit_overflow = isinstance(message, str) and any(phrase in message.lower() for phrase in (
                "context length exceeded", "exceeds the context window", "input length exceeds",
                "exceeds maximum context length", "maximum context length"))
            if path == "/api/chat" and error.code in (400, 413) and explicit_overflow:
                raise ContextLengthError("Backend rejected the request: context length exceeded") from error
        except (ValueError, TypeError):
            pass
        raise RuntimeError(f"Backend rejected {path}: HTTP {error.code}: {detail}") from error


def port_open(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0
