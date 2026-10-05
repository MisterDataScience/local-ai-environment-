"""JSON calls to local backends and loopback port checks."""

import json
import socket
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def api(base, path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read(8192).decode(errors="replace")
        raise RuntimeError(f"Backend rejected {path}: HTTP {error.code}: {detail}") from error


def port_open(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0
