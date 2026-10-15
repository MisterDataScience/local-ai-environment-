"""Managed, localhost-only Captain Work Agent credentials and readiness checks."""
import base64
import json
import os
from pathlib import Path
import secrets
import tempfile
from urllib.request import Request, build_opener, ProxyHandler
import time


AUTH_NAME = 'captain-ui-auth.json'
READY_NAME = 'captain-managed-ready.json'
URL = 'http://127.0.0.1:4096'


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
