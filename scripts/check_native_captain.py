"""Exercise the pinned real OpenCode binary with synthetic local inference.

No model weights, accounts, project imports or external inference are used.
This validates native plugin/API compatibility, not model quality or GPU speed.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE / 'installer'), str(SOURCE / 'installer/payload')]
from captain_config import upgrade
from common import port_open, stop_process
from model_team import upgrade_team
from text_models import upgrade_text_configuration
import work_agent
from team_setup import verify_work_agent

STATUS = {'mode': 'max', 'instance_id': 'native-ci', 'epoch': 0,
          'transitioning': False, 'error': None}
TASKS = [
    {'id': 'calc', 'role': 'analyst', 'objective': 'Calculate 17 times 19.',
     'constraints': 'No commands or edits. Publish one team_note.',
     'evidence': '17 * 20 - 17.', 'deliverable': 'The result and arithmetic.'},
    {'id': 'file-check', 'role': 'reviewer', 'objective': 'Read evidence.txt.',
     'constraints': 'Use the read tool. No commands or edits.',
     'evidence': 'Project file evidence.txt.', 'deliverable': 'The recorded value.'},
]


class SyntheticGateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, project):
        super().__init__(('127.0.0.1', 8001), Handler)
        self.project = project
        self.arrivals = set()
        self.condition = threading.Condition()
        self.failures = []

    def completion(self, body):
        users = '\n'.join(content_text(m.get('content')) for m in body['messages'] if m['role'] == 'user')
        previous = [m for m in body['messages'] if m['role'] == 'tool']
        worker = re.search(r'"task_id"\s*:\s*"(calc|file-check)"', users)
        if worker:
            identifier = worker[1]
            if not previous:
                with self.condition:
                    self.arrivals.add(identifier)
                    self.condition.notify_all()
                    if not self.condition.wait_for(lambda: len(self.arrivals) == 2, timeout=15):
                        raise RuntimeError('Real native worker inference requests did not overlap')
                if identifier == 'calc':
                    return call('team_note', {'text': '17 * 19 = 323.'})
                return call('read', {'filePath': str(self.project / 'evidence.txt')})
            if any('error' in content_text(m.get('content')).lower() for m in previous):
                raise RuntimeError('Worker received an unexpected native tool error: ' + str(previous))
            return {'role': 'assistant', 'content': '17 * 19 = 323.'}
        if 'Native captain protocol check.' not in users:
            return {'role': 'assistant', 'content': 'Local arithmetic check'}  # Native title/summary requests.
        if not previous:
            return call('team_run', {'tasks': TASKS})
        latest = content_text(previous[-1].get('content'))
        if '"cohort"' in latest:
            if latest.count('"status":"completed"') + latest.count('"status": "completed"') != 2:
                raise RuntimeError('Native cohort failed: ' + latest)
            return call('team_retire', {'ids': ['calc', 'file-check']})
        if '"retired"' not in latest:
            raise RuntimeError('Unexpected native captain tool result: ' + latest)
        return {'role': 'assistant', 'content': 'Both results are 323. Workers retired.'}


def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(p.get('text', '') for p in content if isinstance(p, dict))
    return ''


def call(name, arguments):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': 'call-' + name, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, code, body):
        encoded = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == '/control/mode':
            return self.send_json(200, STATUS)
        return self.send_json(404, {'error': 'Synthetic CI service has no such endpoint'})

    def do_POST(self):
        try:
            if self.path != '/v1/chat/completions':
                raise RuntimeError('Unexpected inference endpoint: ' + self.path)
            if self.headers.get('Authorization') != 'Bearer native-ci-key':
                raise RuntimeError('Configured local inference key was not used')
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 2_000_000:
                raise RuntimeError('Unexpected request size')
            body = json.loads(self.rfile.read(length))
            if body['model'] != 'local-ai-captain':
                raise RuntimeError('Native worker/captain used the wrong model')
            message = self.server.completion(body)
            reason = 'tool_calls' if message.get('tool_calls') else 'stop'
            result = {'id': 'chatcmpl-native-ci', 'object': 'chat.completion', 'created': int(time.time()),
                      'model': body['model'], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120},
                      'choices': [{'index': 0, 'message': message, 'finish_reason': reason}]}
            if not body.get('stream'):
                return self.send_json(200, result)
            delta = {'role': 'assistant', 'content': message['content']}
            if message.get('tool_calls'):
                delta['tool_calls'] = [dict(c, index=i) for i, c in enumerate(message['tool_calls'])]
            chunks = [dict(result, object='chat.completion.chunk', choices=[{'index': 0, 'delta': delta, 'finish_reason': None}]),
                      dict(result, object='chat.completion.chunk', choices=[{'index': 0, 'delta': {}, 'finish_reason': reason}])]
            encoded = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(encoded.encode())))
            self.end_headers()
            self.wfile.write(encoded.encode())
        except Exception as error:
            self.server.failures.append(str(error))
            self.send_json(500, {'error': str(error)})


def check(binary):
    # Exercise the same `opencode web` command used by the managed Captain.
    subprocess.run([str(binary), 'web', '--help'],
                   capture_output=True, text=True, timeout=15, check=True)
    if port_open(8001) or port_open(4096):
        raise RuntimeError('Native CI check requires unoccupied loopback ports; no service was stopped')
    with tempfile.TemporaryDirectory(prefix='native-captain-') as folder:
        root = Path(folder)
        project = root / 'project'; project.mkdir()
        (project / 'evidence.txt').write_text('Recorded evidence: 323.\n')
        control = root / 'control'; control.mkdir()
        # Copy the real plugin modules and contract resources, not test replacements.
        for source in (SOURCE / 'installer').iterdir():
            if source.is_file() and source.suffix in {'.mjs', '.txt'}:
                shutil.copy2(source, control / source.name)
        config = upgrade(upgrade_team(upgrade_text_configuration({'api_key': 'native-ci-key'})))
        # Simulate requests whose browser page/API share one tailnet origin.
        remote_origin = 'https://native-ci.example.ts.net:10000'
        config['remote_access'] = {
            'enabled': True, 'hostname': 'native-ci.example.ts.net',
            'captain_url': remote_origin}
        settings = work_agent.configuration(config, list(config['text_models']), 'max', root, STATUS)
        if settings.get('server', {}).get('cors') != [remote_origin]:
            raise RuntimeError('OpenCode did not restrict remote CORS to the private Captain origin')
        env = work_agent.environment(root, config, settings)
        env.update(OPENCODE_SERVER_USERNAME='opencode', OPENCODE_SERVER_PASSWORD='native-ci-password')
        token = base64.b64encode(b'opencode:native-ci-password').decode()
        def native(path, body=None):
            request = Request('http://127.0.0.1:4096' + path,
                data=None if body is None else json.dumps(body).encode(),
                headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'})
            with urlopen(request, timeout=90) as response:
                return json.load(response)
        server = SyntheticGateway(project)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        process = None
        try:
            with (root / 'opencode.log').open('w') as log:
                process = subprocess.Popen([str(binary), 'web', '--hostname', '127.0.0.1', '--port', '4096'],
                    cwd=project, env=env, stdout=log, stderr=log, start_new_session=True)
                verify_work_agent(process, env, True)
                # Real native OpenCode, simulated incoming HTTPS reverse-proxy
                # browser Origin and Host. Never infer that this tests Tailscale
                # routing or an actual second-device Safari/Windows browser.
                remote_headers = {'Authorization': 'Basic ' + token,
                                  'Origin': remote_origin,
                                  'Host': 'native-ci.example.ts.net:10000'}
                with urlopen(Request('http://127.0.0.1:4096/',
                                     headers=remote_headers), timeout=10) as response:
                    ui_type = response.headers.get('Content-Type', '')
                    ui_final = response.geturl()
                    ui_sample = response.read(4096).lower()
                if not ui_final.startswith('http://127.0.0.1:4096/') or (
                        'text/html' not in ui_type and b'<html' not in ui_sample):
                    raise RuntimeError('Pinned OpenCode web did not serve a local Captain HTML interface')
                with urlopen(Request('http://127.0.0.1:4096/agent',
                                     headers=remote_headers), timeout=10) as response:
                    remote_agents = json.load(response)
                if not {'plan', 'build'}.issubset({a.get('name') for a in remote_agents}):
                    raise RuntimeError('Private tailnet same-origin browser cannot see native Plan/Build')
                # A browser loaded from the same proxy hostname/port as
                # its API does not need Access-Control-Allow-Origin. What
                # matters is real authenticated API and SSE compatibility.
                with urlopen(Request('http://127.0.0.1:4096/event',
                                     headers=remote_headers), timeout=10) as response:
                    if 'text/event-stream' not in response.headers.get('Content-Type', ''):
                        raise RuntimeError('Remote-origin event stream was not established')
                session = native('/session', {'title': 'Native captain CI'})['id']
                answer = native('/session/' + session + '/message', {'agent': 'plan', 'parts': [
                    {'type': 'text', 'text': 'Native captain protocol check. Dispatch the two supplied workers and retire them.'}]})
                if answer.get('info', {}).get('error'):
                    raise RuntimeError('Native parent failed: ' + str(answer['info']['error']))
                history = native('/session/' + session + '/message')
                tools = [p for m in history for p in m['parts'] if p['type'] == 'tool']
                dispatch = next((p for p in tools if p['tool'] == 'team_run' and p['state']['status'] == 'completed'), None)
                retired = next((p for p in tools if p['tool'] == 'team_retire' and p['state']['status'] == 'completed'), None)
                if not dispatch or not retired:
                    raise RuntimeError('Real OpenCode did not execute native dispatch/retirement: ' + str(tools))
                tasks = json.loads(dispatch['state']['output'])['tasks']
                if len(tasks) != 2 or any(t['status'] != 'completed' for t in tasks):
                    raise RuntimeError('Native workers did not complete: ' + str(tasks))
                for task in tasks:
                    report = json.loads(Path(task['report']).read_text())
                    expected = 'read' if task['id'] == 'file-check' else 'team_note'
                    if not any(t['tool'] == expected and t['state']['status'] == 'completed' for t in report['native_tools']):
                        raise RuntimeError('Native worker tool did not execute: ' + expected)
                if set(json.loads(retired['state']['output'])['retired']) != {'calc', 'file-check'}:
                    raise RuntimeError('Native retirement did not cover both workers')
                if server.failures:
                    raise RuntimeError('Synthetic gateway failures: ' + str(server.failures))
                print('Real OpenCode: two overlapping workers, native read/note tools, reports and retirement verified.')
        except Exception:
            print((root / 'opencode.log').read_text()[-12000:], file=sys.stderr)
            raise
        finally:
            if process:
                stop_process(process, timeout=5)
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    check(parser.parse_args().binary.resolve(strict=True))
