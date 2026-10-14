"""Prepare verified local artifacts and check the native OpenCode policy."""
import base64
import json
import time
import secrets
import subprocess
import re
from fnmatch import fnmatchcase
from urllib.request import Request, urlopen
from urllib.error import URLError

from common import ollama_binary, ollama_environment, port_open, stop_process


def prepare_models(root, presets, download, run, http):
    from model_team import CODER, CODER_FILE, CODER_URL, CODER_SHA256, REGISTRY_DIGESTS
    models = list(dict.fromkeys(p['model'] for p in presets.values() if p.get('backend', 'ollama') == 'ollama'))
    base = 'http://127.0.0.1:11435'
    report = {}
    for model in models:
        if model == CODER:
            artifact = root / 'downloads' / CODER_FILE
            download(CODER_URL, artifact, CODER_SHA256)
            modelfile = root / 'control/coder.Modelfile'
            modelfile.write_text('FROM ' + json.dumps(str(artifact)) + '\n')
            run([ollama_binary(root), 'create', CODER, '-f', modelfile], env=ollama_environment(root))
        else:
            run([ollama_binary(root), 'pull', model], env=ollama_environment(root))
        if model not in REGISTRY_DIGESTS and model != CODER:
            continue
        installed = next((m for m in http(base + '/api/tags')['models'] if m['name'] == model), None)
        if not installed:
            raise RuntimeError('Model missing after preparation: ' + model)
        digest = installed.get('digest', '').removeprefix('sha256:')
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise RuntimeError('Missing full installed model digest: ' + model)
        if model in REGISTRY_DIGESTS and not digest.startswith(REGISTRY_DIGESTS[model]):
            raise RuntimeError('Published model tag changed; review the team manifest before installing: ' + model)
        shown = http(base + '/api/show', {'model': model})
        expected_family = 'gemma4' if model == CODER else 'qwen35'
        if shown.get('details', {}).get('family') != expected_family:
            raise RuntimeError('Unexpected model architecture: ' + model)
        if shown.get('details', {}).get('quantization_level') != 'Q4_K_M':
            raise RuntimeError('Unexpected model quantisation: ' + model)
        if model.endswith(':4B') and 'tools' not in shown.get('capabilities', []):
            raise RuntimeError('Coordinator does not advertise tool calling')
        report[model] = {'digest': digest, 'details': shown['details'],
                         'capabilities': shown.get('capabilities', []),
                         'source_sha256': CODER_SHA256 if model == CODER else None}
    (root / 'control/model-artifacts.json').write_text(json.dumps(report, indent=2) + '\n')


def verify_work_agent(process, env, enabled, timeout=90):
    """Read effective native agents, not merely the JSON we generated."""
    if not enabled:
        return
    token = base64.b64encode(('opencode:' + env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('OpenCode exited before model team validation')
        try:
            request = Request('http://127.0.0.1:4096/agent', headers={'Authorization': 'Basic ' + token})
            with urlopen(request, timeout=3) as response:
                agents = {a['name']: a for a in json.load(response)}
            for role in ('analyst', 'document'):
                rules = agents.get(role, {}).get('permission', [])
                tool_rules = [r for r in rules if r['permission'] != 'external_directory']
                if not tool_rules or tool_rules[-1] != {'permission': '*', 'pattern': '*', 'action': 'deny'}:
                    raise RuntimeError('Specialist tool permissions were not loaded')
            coder = agents.get('coder', {})
            def action(permission, target='*'):
                matches = [r for r in coder.get('permission', []) if r['permission'] in ('*', permission)
                           and fnmatchcase(target, r['pattern'])]
                return matches[-1]['action'] if matches else None
            for permission, target, expected in [('read', 'example.py', 'allow'), ('read', '.env', 'deny'),
                    ('glob', '*', 'allow'), ('grep', '*', 'allow'), ('edit', '*', 'ask'),
                    ('bash', '*', 'ask'), ('task', '*', 'deny'), ('webfetch', '*', 'deny'),
                    ('external_directory', '/outside-project', 'deny')]:
                if action(permission, target) != expected:
                    raise RuntimeError('Coder native approval permissions were not loaded: ' + permission)
            if coder.get('steps') != 12:
                raise RuntimeError('Coder step limit was not loaded')
            for parent in ('plan', 'build'):
                rules = agents.get(parent, {}).get('permission', [])
                for role in ('analyst', 'coder', 'document'):
                    matches = [r for r in rules if r['permission'] in ('*', 'task') and r['pattern'] in ('*', role)]
                    if not matches or matches[-1]['action'] != 'allow':
                        raise RuntimeError('OpenCode model team policy did not load; delegation remains disabled')
                for name in ('local_image', 'local_video', 'local_speech'):
                    matches = [r for r in rules if r['permission'] in ('*', name) and r['pattern'] == '*']
                    if not matches or matches[-1]['action'] != 'ask':
                        raise RuntimeError('Coordinator media approval permissions were not loaded')
            configured = json.loads(env.get('OPENCODE_CONFIG_CONTENT', '{}'))
            if 'captain-coder' in configured.get('agent', {}):
                for role in ('researcher', 'analyst', 'coder', 'writer', 'reviewer'):
                    worker = agents.get('captain-' + role, {})
                    if not worker or worker.get('steps') != 12:
                        raise RuntimeError('Captain worker configuration did not load: ' + role)
                    for tool in ('task', 'team_run', 'team_retire', 'external_directory', 'webfetch'):
                        rules = [r for r in worker.get('permission', []) if fnmatchcase(tool, r['permission'])
                                 and r['pattern'] == '*']
                        if not rules or rules[-1]['action'] != 'deny':
                            raise RuntimeError('Captain worker permission did not load: ' + tool)
                for parent in ('plan', 'build'):
                    rules = [r for r in agents[parent]['permission'] if fnmatchcase('team_run', r['permission'])
                             and r['pattern'] == '*']
                    if not rules or rules[-1]['action'] != 'allow':
                        raise RuntimeError('Captain dispatch policy did not initialize')
            return
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    raise RuntimeError('OpenCode model team startup timed out')


def verify_native_handoffs(root, config):
    """Mac acceptance: actual OpenCode -> gateway -> specialist -> parent."""
    import work_agent
    from common import http
    if not config.get('model_team', {}).get('enabled'):
        return []
    if port_open(4096):
        raise RuntimeError('Close the work agent before native team acceptance')
    status = http('http://127.0.0.1:8001/control/mode', key=config['api_key'])
    visible = http('http://127.0.0.1:8001/v1/models', key=config['api_key'])['data']
    from model_team import team_roles
    roles = team_roles(config, [m['id'] for m in visible])
    settings = work_agent.configuration(config, [m['id'] for m in visible], status['mode'], root, status)
    env = work_agent.environment(root, config, settings)
    env.update(OPENCODE_SERVER_USERNAME='opencode', OPENCODE_SERVER_PASSWORD=secrets.token_urlsafe(24))
    folder = root / 'work-agent/acceptance'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'coder-acceptance.txt').write_text('Acceptance evidence: 17 * 20 - 17 = 323.\n')
    token = base64.b64encode(('opencode:' + env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
    def native(path, body=None):
        request = Request('http://127.0.0.1:4096' + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'})
        with urlopen(request, timeout=4000) as response:
            return json.load(response)
    binary = root / 'tools/opencode' / work_agent.VERSION / 'opencode'
    with (root / 'logs/opencode-acceptance.log').open('a') as log:
        process = subprocess.Popen([str(binary), 'serve', '--hostname', '127.0.0.1', '--port', '4096'],
                                   cwd=folder, env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            verify_work_agent(process, env, True)
            checks = []
            for role in ('analyst', 'coder'):
                started = time.monotonic()
                session = native('/session', {'title': 'Local model team acceptance: ' + role})['id']
                packet = json.dumps({'objective': ('Read coder-acceptance.txt and explain its arithmetic.'
                    if role == 'coder' else 'Explain why 17 * 19 equals 323.'),
                    'constraints': ('Use the read tool. Do not edit or execute commands.' if role == 'coder'
                                    else 'Short answer. Do not execute tools.'),
                    'evidence': 'Project file: coder-acceptance.txt' if role == 'coder' else '17 * 20 - 17 = 323.',
                    'completed': '', 'remaining': 'Explain the supplied arithmetic.',
                    'result': 'A short explanation and an honest validation statement.',
                    'facts': ['17 * 20 - 17 = 323.'], 'assumptions': [], 'unknowns': [],
                    'references': [{'path': 'coder-acceptance.txt', 'symbol': ''}] if role == 'coder' else [],
                    'acceptance': [{'id': 'A1', 'requirement': 'Explain the supplied arithmetic.',
                        'source_quote': '', 'verification': {'kind': 'inspection' if role == 'coder' else 'analysis',
                                                           'command': ''}}]})
                prompt = ('Acceptance check. Call the task tool exactly once with subagent_type ' + role
                          + ', description "Check supplied arithmetic", and prompt set to this JSON string: '
                          + packet + '. Wait for its result, then briefly report it. Do not answer before delegating.')
                response = native('/session/' + session + '/message', {'agent': 'plan',
                    'parts': [{'type': 'text', 'text': prompt}]})
                if response.get('info', {}).get('error'):
                    raise RuntimeError('OpenCode native team inference failed: ' + role)
                messages = native('/session/' + session + '/message')
                tasks = [p for m in messages for p in m['parts'] if p['type'] == 'tool' and p.get('tool') == 'task']
                if len(tasks) != 1 or tasks[0]['state']['status'] != 'completed':
                    raise RuntimeError('Coordinator did not complete exactly one native handoff: ' + role)
                task = tasks[0]['state']
                if task['input'].get('subagent_type') != role:
                    raise RuntimeError('Coordinator selected the wrong specialist')
                child = task.get('metadata', {}).get('sessionId')
                if not child:
                    raise RuntimeError('OpenCode did not preserve child session identity')
                if task.get('metadata', {}).get('localTeamReview') != 'ready_for_review':
                    raise RuntimeError('Native specialist return did not satisfy its handoff contract')
                child_messages = native('/session/' + child + '/message')
                outputs = [m for m in child_messages if m['info']['role'] == 'assistant']
                expected = roles[role]
                if not outputs or any(m['info']['modelID'] != expected or
                    m['info'].get('providerID') != 'local-ai-gateway' or m['info'].get('error') for m in outputs):
                    raise RuntimeError('Native specialist used an unexpected model')
                if not any(p['type'] == 'text' and p.get('text', '').strip() for m in outputs for p in m['parts']):
                    raise RuntimeError('Native specialist returned no text')
                child_tools = [p for m in child_messages for p in m['parts'] if p['type'] == 'tool']
                if role == 'analyst' and child_tools:
                    raise RuntimeError('Native analyst attempted a tool')
                if role == 'coder' and (not any(p.get('tool') == 'read' and p.get('state', {}).get('status') == 'completed'
                                               for p in child_tools)
                    or any(p.get('tool') not in ('read', 'glob', 'grep') for p in child_tools)):
                    raise RuntimeError('Native Plan coder did not complete permitted file inspection')
                if not any(p['type'] == 'text' and p.get('text', '').strip() for p in response.get('parts', [])):
                    raise RuntimeError('Coordinator did not return a final answer')
                checks.append({'name': 'opencode-handoff-' + role, 'status': 'passed',
                               'seconds': round(time.monotonic() - started, 1)})
            return checks
        finally:
            stop_process(process, timeout=15)
