"""Managed, localhost-only Captain Work Agent credentials and readiness checks."""
import base64
import json
import os
from pathlib import Path
import secrets
import tempfile
from urllib.request import Request, build_opener, ProxyHandler
import time
import logging


AUTH_NAME = 'captain-ui-auth.json'
READY_NAME = 'captain-managed-ready.json'
URL = 'http://127.0.0.1:4096'


def resumed_from_sleep(last_monotonic, last_wall, now_monotonic, now_wall):
    # On the target Mac, monotonic time excludes system sleep. A slow blocking
    # operation advances both clocks and must not reset the failure streak.
    # A large forward wall-clock correction may grant grace too, which is safe.
    return (now_wall - last_wall) - (now_monotonic - last_monotonic) > 30


class CaptainWatchdog:
    """Probe the control API, never inference, before requesting a restart."""
    def __init__(self, interval=30, threshold=3, grace=60, timeout=3):
        self.interval = interval
        self.threshold = threshold
        self.grace = grace
        self.timeout = timeout
        self.process = None
        self.failures = 0
        self.next_check = 0

    def check(self, root, process, mode, *, now=None, resumed=False):
        now = time.monotonic() if now is None else now
        if process is not self.process:
            self.process = process
            self.failures = 0
            self.next_check = now + self.grace
        if process is None or process.poll() is not None:
            self.failures = 0
            return False
        # An unavailable gateway, mode transition or intentional Gaming mode
        # must not look like a frozen Captain. Startup/wake gets a fresh grace.
        if (resumed or not isinstance(mode, dict) or
                mode.get('mode') not in {'normal', 'max'} or
                mode.get('transitioning') is not False or mode.get('error') is not None):
            self.failures = 0
            self.next_check = now + self.grace
            return False
        if now < self.next_check:
            return False
        self.next_check = now + self.interval
        try:
            agent_status(root, timeout=self.timeout)
        except (OSError, RuntimeError, ValueError, KeyError):
            self.failures += 1
            # Do not log response bodies, credential errors or request headers.
            logging.warning('Captain control API unresponsive (%s/%s probes).',
                            self.failures, self.threshold)
            if self.failures >= self.threshold:
                self.failures = 0
                self.next_check = now + self.grace
                return True
        else:
            self.failures = 0
        return False


def credentials(root):
    path = Path(root) / 'control' / AUTH_NAME
    if path.is_symlink():
        raise RuntimeError('Refusing symlink for Captain UI credentials')
    if path.exists():
        if not path.is_file() or path.stat().st_mode & 0o077:
            raise RuntimeError('Captain UI credential file must be private (0600)')
        value = json.loads(path.read_text())
        if value.get('username') != 'opencode' or not isinstance(value.get('password'), str) or len(value['password']) < 32:
            raise RuntimeError('Captain UI credential file is invalid')
        return value
    value = {'username': 'opencode', 'password': secrets.token_urlsafe(36)}
    fd, name = tempfile.mkstemp(prefix='.captain-auth-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(value, file)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        # A competing installer/runtime must never overwrite already-created credentials.
        try:
            os.link(name, path)
        except FileExistsError:
            return credentials(root)
        return value
    finally:
        Path(name).unlink(missing_ok=True)


def agent_status(root, timeout=5):
    auth = credentials(root)
    token = base64.b64encode((auth['username'] + ':' + auth['password']).encode()).decode()
    request = Request(URL + '/agent', headers={'Authorization': 'Basic ' + token})
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        agents = json.load(response)
    if not isinstance(agents, list):
        raise RuntimeError('Captain UI agent inventory is invalid')
    names = {item.get('name') for item in agents if isinstance(item, dict)}
    if not {'plan', 'build'}.issubset(names):
        raise RuntimeError('Captain UI lacks the Plan and Build agents')
    return {'captain_agent_endpoint': 'passed', 'native_agents': sorted(names)}


def wait_for_agent(root, process, timeout=120):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Managed Captain Work Agent exited; inspect logs/captain.log')
        try:
            result = agent_status(root, timeout=3)
            # The managed process publishes this only after native MCP and policy verification.
            if (Path(root) / 'control' / READY_NAME).is_file():
                return result
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            last = error
        time.sleep(1)
    raise RuntimeError('Captain UI did not become ready: ' + str(last))
