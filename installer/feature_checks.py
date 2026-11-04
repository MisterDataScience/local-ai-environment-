"""Native feature acceptance. Unit tests do not substitute for these checks."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

from common import (http, launch, ollama_binary, ollama_environment, stop_process,
                    wait_ready, webui_environment)
from feature_state import effective_config, atomic_json


@contextmanager
def services(root, features, *, captain=False):
    """Temporary loopback services owned and retired by the locked installer."""
    config = json.loads((root / 'control/config.json').read_text())
    config = effective_config(root, config, testing=features)
    env = dict(os.environ, LOCAL_AI_ACCEPTANCE_FEATURES=','.join(features))
    processes = []
    import resource_modes
    saved = resource_modes.load(root / 'control')
    resource_modes.save(root / 'control', 'max')
    try:
        process = launch([ollama_binary(root), 'serve'], root, root / 'logs/feature-ollama.log', ollama_environment(root))
        processes.append(process)
        wait_ready('http://127.0.0.1:11435/api/version', process)
        process = launch([root / 'control/.venv/bin/python', root / 'control/gateway.py'],
                         root / 'control', root / 'logs/feature-gateway.log', env)
        processes.append(process)
        wait_ready('http://127.0.0.1:8001/health', process)
        if captain:
            process = launch([root / 'webui/.venv/bin/open-webui', 'serve', '--host', '127.0.0.1', '--port', '8081'],
                             root / 'webui', root / 'logs/feature-webui.log', webui_environment(root, config))
            processes.append(process)
            wait_ready('http://127.0.0.1:8081/health', process, timeout=600)
            from managed_captain import wait_for_agent
            process = launch([root / 'control/.venv/bin/python', root / 'control/work_agent.py', '--root', root, '--managed'],
                             root / 'control', root / 'logs/feature-captain.log', env)
            processes.append(process)
            wait_for_agent(root, process)
        yield config
    finally:
        try:
            for process in reversed(processes):
                stop_process(process, timeout=4200)
        finally:
            resource_modes.save(root / 'control', saved)


def speech(root, config):
    import speech as engine
    # Run the actual offline model, then validate its bytes and saved output.
    control = root / 'control'
    (control / 'media').mkdir(exist_ok=True, mode=0o700)
    prepared = engine.request(config, control, 'This is a local speech acceptance check.')
    result = engine.generate(config, control, prepared)
    return {'speech_generation_and_wav_validation': 'passed', 'output': result,
            'listening_quality': 'not_run'}


def media(root):
    from installer import verify_text_residency
    from text_models import configured_text_models
    results = {}
    with services(root, ('media',)) as config:
        presets = configured_text_models(config)
        for kind, prompt, extension in (
            ('image', '/image A red toy car on a white table.', '.png'),
            ('video', '/video A red toy car moves slowly across a white table.', '.mp4')):
            answer = http('http://127.0.0.1:8001/v1/chat/completions',
                {'model': 'local-ai', 'messages': [{'role': 'user', 'content': prompt}]},
                key=config['api_key'], timeout=4000)
            content = answer['choices'][0]['message']['content']
            if extension not in content:
                raise RuntimeError('Native media generation did not return a saved asset')
            verify_text_residency(config, presets, None)
            answer = http('http://127.0.0.1:8001/v1/chat/completions',
                {'model': 'local-ai', 'messages': [{'role': 'user', 'content': 'Reply with one sentence about art.'}]},
                key=config['api_key'], timeout=4000)
            if not answer['choices'][0]['message']['content'].strip():
                raise RuntimeError('Text generation failed after media handoff')
            verify_text_residency(config, presets, 'local-ai')
            results[kind + '_and_text_handoff'] = 'passed'
    return results


def conversation(root):
    from conversation_check import check
    with services(root, ('conversation',)):
        if not check(root):
            raise RuntimeError('Native conversation speech/STT/VAD round trip failed')
    return {'speech_stt_vad_roundtrip': 'passed', 'microphone_and_barge_in': 'not_run'}


def web_request(config, path, payload=None):
    request = Request('http://127.0.0.1:8090' + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + config['web']['api_key'], 'Content-Type': 'application/json'})
    with build_opener(ProxyHandler({})).open(request, timeout=45) as response:
        return json.load(response)



def recover_web_acceptance(root):
    """Recover a SIGKILL/power loss during the bounded tunnel-outage check."""
    from feature_state import safe_path
    from web_access import save, start
    journal = safe_path(root / 'web/acceptance-recovery.json')
    if not journal.exists():
        return
    recovery = json.loads(journal.read_text())
    name = recovery['auth_file']
    if Path(name).name != name or not name.startswith('acceptance-auth-') or not name.endswith('.toml'):
        raise RuntimeError('Invalid VPN acceptance recovery journal; preserve it for review')
    auth_path = safe_path(root / 'web' / name)
    save(root / 'web/compose.json', recovery['original_spec'])
    start(root)
    auth_path.unlink(missing_ok=True)
    journal.unlink()


def web(root, config):
    """Exercise retrieval and a real tunnel outage in the owned VPN namespace."""
    from web_access import compose, status
    recover_web_acceptance(root)
    spec = json.loads((root / 'web/compose.json').read_text())
    for name in ('reader', 'search'):
        if spec['services'][name].get('network_mode') != 'service:vpn':
            raise RuntimeError('Web service escaped its VPN namespace')
    if spec['services']['vpn'].get('environment', {}).get('FIREWALL') != 'on':
        raise RuntimeError('VPN firewall is not enabled')
    if status(root).get('status') != 'ready':
        raise RuntimeError('VPN is not healthy')
    # Both requests go through the VPN-only reader, never host web requests.
    if not web_request(config, '/read', {'url': 'https://example.com'}):
        raise RuntimeError('VPN page acceptance returned no result')
    if not web_request(config, '/search', {'query': 'example domain'}):
        raise RuntimeError('VPN search acceptance returned no result')
    import secrets
    import tempfile
    from web_access import save, start, docker_command
    key = secrets.token_urlsafe(32)
    # Temporary route-scoped control credential. Port 8000 is never published.
    fd, name = tempfile.mkstemp(dir=root / 'web', prefix='acceptance-auth-', suffix='.toml')
    auth_path = Path(name)
    with os.fdopen(fd, 'w') as output:
        output.write('[[roles]]\nname = "installer-acceptance"\nroutes = ["PUT /v1/vpn/status"]\nauth = "apikey"\napikey = "' + key + '"\n')
    original_spec = json.loads(json.dumps(spec))
    journal = root / 'web/acceptance-recovery.json'
    atomic_json(journal, {'original_spec': original_spec, 'auth_file': auth_path.name})
    spec['services']['vpn'].setdefault('volumes', []).append(str(auth_path) + ':/gluetun/auth/config.toml:ro')
    def control(state):
        # Secret travels through stdin, never process arguments, logs or output.
        project = 'local-ai-web-' + __import__('hashlib').sha256(str(root).encode()).hexdigest()[:10]
        code = ("import json,sys;from urllib.request import Request,urlopen;v=json.load(sys.stdin);"
                "r=Request('http://127.0.0.1:8000/v1/vpn/status',method='PUT',"
                "data=json.dumps({'status':v['status']}).encode(),"
                "headers={'X-API-Key':v['key'],'Content-Type':'application/json'});"
                "urlopen(r,timeout=15).close()")
        import subprocess
        subprocess.run([docker_command(), 'compose', '--project-name', project, '--file',
            str(root / 'web/compose.json'), 'exec', '-T', 'reader', 'python', '-c', code],
            input=json.dumps({'key': key, 'status': state}), text=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=True)
    try:
        save(root / 'web/compose.json', spec)
        start(root)
        # Gluetun keeps its firewall enabled when its tunnel is stopped.
        control('stopped')
        deadline = time.monotonic() + 30
        while True:
            try:
                healthy = status(root).get('status') == 'ready'
            except (OSError, ValueError, HTTPError, URLError):
                healthy = False
            if not healthy:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('VPN did not stop for fail-closed acceptance')
            time.sleep(1)
        try:
            web_request(config, '/read', {'url': 'https://example.com'})
        except (HTTPError, URLError, OSError):
            pass
        else:
            raise RuntimeError('Reader accepted a page while VPN was stopped')
        # Observe external DNS and raw HTTPS failure inside the same namespace.
        script = ("import socket; failures=0\n"
                  "for address in [('1.1.1.1',443),('8.8.8.8',53)]:\n"
                  " try: socket.create_connection(address,timeout=3).close()\n"
                  " except OSError: failures+=1\n"
                  "assert failures==2, 'Traffic escaped VPN firewall'\n")
        compose(root, 'exec', '-T', 'reader', 'python', '-c', script, timeout=20)
    finally:
        # Always restore the owner's original stack and remove the test credential.
        recover_web_acceptance(root)
    return {'vpn_search_page': 'passed', 'tunnel_drop_fail_closed': 'passed',
            'external_dns_and_https_blocked_without_tunnel': 'passed',
            'packet_capture_dns_leak': 'not_run'}



class MCP:
    """Bounded streamable-HTTP checks, with session handling and no redirects."""
    def __init__(self, url, headers=None):
        from context_settings import NoRedirect
        self.url, self.headers, self.session = url, headers or {}, None
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.sequence = 0

    def call(self, method, params=None, *, notification=False):
        self.sequence += 1
        body = {'jsonrpc': '2.0', 'method': method}
        if not notification:
            body['id'] = self.sequence
        if params is not None:
            body['params'] = params
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', **self.headers}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        request = Request(self.url, data=json.dumps(body).encode(), headers=headers)
        with self.opener.open(request, timeout=90) as response:
            self.session = response.headers.get('Mcp-Session-Id', self.session)
            raw = response.read(20_000_001)
        if notification:
            return {}
        if len(raw) > 20_000_000:
            raise RuntimeError('Oversized MCP acceptance response')
        decoded = raw.decode().strip()
        candidates = [decoded] if decoded.startswith('{') else [
            line.removeprefix('data: ').strip() for line in decoded.splitlines() if line.startswith('data: ')]
        for line in candidates:
            if not line.startswith('{'):
                continue
            result = json.loads(line)
            if result.get('id') != body['id']:
                continue
            if result.get('error') or result.get('result', {}).get('isError'):
                raise RuntimeError('MCP acceptance request failed')
            return result.get('result', {})
        raise RuntimeError('MCP acceptance returned no matching response')

    def initialise(self):
        self.call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'local-ai-acceptance', 'version': '1'}})
        self.call('notifications/initialized', notification=True)


def browser(root):
    import base64
    from io import BytesIO
    from PIL import Image
    from browser_setup import URL
    spec = json.loads((root / 'web/compose.json').read_text())
    if spec['services']['browser'].get('network_mode') != 'service:vpn':
        raise RuntimeError('Browser is outside the VPN network namespace')
    client = MCP(URL)
    client.initialise()
    try:
        client.call('tools/call', {'name': 'browser_navigate', 'arguments': {'url': 'https://example.com'}})
        snapshot = client.call('tools/call', {'name': 'browser_snapshot', 'arguments': {}})
        if 'Example Domain' not in json.dumps(snapshot):
            raise RuntimeError('Browser did not render the acceptance page')
        screenshot = client.call('tools/call', {'name': 'browser_take_screenshot', 'arguments': {'type': 'png'}})
        picture = next((part for part in screenshot.get('content', []) if part.get('type') == 'image'), None)
        if not picture:
            raise RuntimeError('Browser did not return rendered screenshot pixels')
        with Image.open(BytesIO(base64.b64decode(picture['data'], validate=True))) as image:
            image.verify()
    finally:
        client.call('tools/call', {'name': 'browser_close', 'arguments': {}})
    return {'vpn_namespace': 'passed', 'mcp_initialise': 'passed', 'rendered_page_and_screenshot': 'passed'}


def remote(root):
    from remote_access import verify_remote_access
    with services(root, ('remote',), captain=True) as config:
        verify_remote_access(root, config['remote_access'])
    return {'private_https_and_captain_auth': 'passed', 'other_tailnet_device': 'not_run'}



def github(root):
    """Validate owner identity and official MCP tools without writing to GitHub."""
    from account_tools import connection, URL
    info = connection(root)
    client = MCP(URL, {'Authorization': 'Bearer ' + info['key'], **info.get('headers', {})})
    client.initialise()
    listing = client.call('tools/list')
    if 'get_me' not in {tool.get('name') for tool in listing.get('tools', [])}:
        raise RuntimeError('GitHub MCP identity tool is unavailable')
    identity = client.call('tools/call', {'name': 'get_me', 'arguments': {}})
    if not identity.get('content') and not identity.get('structuredContent'):
        raise RuntimeError('GitHub identity check returned no identity')
    return {'mcp_auth_and_identity': 'passed', 'denied_and_approved_write': 'not_run'}


def discord_live(root, timeout=600):
    import selectors
    from conversation import launch as launch_bridge
    from discord_runtime import start_adapter, close_bridge
    from managed_captain import credentials
    bridge = process = None
    print('Join the private local-ai Discord voice channel. Speak, wait for audible playback, then interrupt the playing reply.')
    print('The diagnostic waits up to ten minutes and records connection, received speech, playback and interruption separately.')
    try:
        with services(root, ('discord',), captain=True) as config:
            bridge, _ = launch_bridge(root, credentials(root)['password'], config)
            process = start_adapter(root, config, bridge.app.key, acceptance=True)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if not selector.select(timeout=min(2, max(0, deadline - time.monotonic()))):
                        if process.poll() is not None:
                            break
                        continue
                    line = process.stdout.readline(8192)
                    if not line:
                        break
                    try:
                        result = json.loads(line)
                    except ValueError:
                        continue
                    expected = {'private_voice_connection', 'owner_speech_received', 'response_played', 'interruption'}
                    checks = result.get('checks', {})
                    if result.get('acceptance') == 'passed' and set(checks) == expected and all(value is True for value in checks.values()):
                        return {key: 'passed' for key in expected}
            raise RuntimeError('The private Discord call did not complete all required observations')
    finally:
        if process:
            stop_process(process, timeout=30)
            if process.stdout:
                process.stdout.close()
        if bridge:
            close_bridge(bridge)
