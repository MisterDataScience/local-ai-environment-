"""Verify live native MCP connections and effective permission rules."""
import base64
from fnmatch import fnmatchcase
import json
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

TOOLS = {'projectpdf_read_pdf': 'allow', 'projectfiles_transfer_file': 'ask',
         'projectfiles_list_files': 'allow', 'projectvision_inspect_image': 'allow'}

def expected_capabilities(settings):
    """Selected MCP servers and representative role permissions to validate."""
    servers = ['projectpdf', 'projectfiles', 'projectvision']
    tools = dict(TOOLS)
    if 'playwright' in settings.get('mcp', {}) and settings['mcp']['playwright'].get('enabled'):
        servers.append('playwright')
        tools.update(playwright_browser_snapshot='allow', playwright_browser_navigate='ask',
                     playwright_browser_type='ask', playwright_browser_evaluate='ask')
    return servers, tools



def verify(process, env, timeout=90):
    settings = json.loads(env.get('OPENCODE_CONFIG_CONTENT', '{}'))
    servers, tools = expected_capabilities(settings)
    token = base64.b64encode(('opencode:' + env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
    def get(path):
        with urlopen(Request('http://127.0.0.1:4096' + path, headers={'Authorization': 'Basic ' + token}), timeout=5) as response:
            return json.load(response)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Work Agent exited before capability validation')
        try:
            status = get('/mcp')
            if any(status.get(server, {}).get('status') != 'connected' for server in servers):
                time.sleep(0.25)
                continue
            agents = {agent['name']: agent for agent in get('/agent')}
            for role in ('plan', 'build'):
                if role not in agents:
                    raise RuntimeError('Required Work Agent role missing')
                for tool, expected in tools.items():
                    matches = [rule for rule in agents[role]['permission'] if fnmatchcase(tool, rule['permission']) and rule['pattern'] == '*']
                    if not matches or matches[-1]['action'] != expected:
                        raise RuntimeError('Native capability permission mismatch: ' + role + '/' + tool)
            return
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    raise RuntimeError('Required PDF, transfer, vision or browser MCP connection not ready')
