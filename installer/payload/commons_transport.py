"""Interruptible, proxy-free local inference for explicitly opened Commons.

No arbitrary URL, remote provider, command, plugin or model tool is accepted.
The executor retains its lease until the request socket has actually returned.
"""
import http.client
import json
import socket
import threading
import time


class Turn:
    def __init__(self, deadline):
        self.deadline = deadline
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.sock = None

    def is_set(self):
        return self.cancelled.is_set() or time.monotonic() >= self.deadline

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.sock:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.sock.close()

    def api(self, base, path, payload, timeout=1800):
        endpoints = {"http://127.0.0.1:11436": (11436, "/api/chat"),
                     "http://127.0.0.1:11437": (11437, "/v1/chat/completions")}
        if base not in endpoints or path != endpoints[base][1] or self.is_set():
            raise RuntimeError("Commons local inference cancelled or endpoint denied")
        payload = dict(payload, stream=False)
        if payload.get("tools") or payload.get("tool_choice"):
            raise PermissionError("Commons cannot delegate tools to a model backend")
        remaining = min(timeout, self.deadline-time.monotonic())
        if remaining <= 0:
            raise RuntimeError("Commons turn deadline reached")
        connection = http.client.HTTPConnection("127.0.0.1", endpoints[base][0], timeout=min(remaining, 3))
        try:
            connection.connect()
            connection.sock.settimeout(remaining)
            with self.lock:
                self.sock = connection.sock
                if self.is_set():
                    raise RuntimeError("Commons cancelled")
            connection.request("POST", path, body=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError("Local Commons backend rejected the request")
            raw = response.read(2*1024*1024+1)
            if len(raw) > 2*1024*1024 or self.is_set():
                raise RuntimeError("Commons output exceeded its limit or was cancelled")
            return json.loads(raw)
        finally:
            with self.lock:
                self.sock = None
            connection.close()
