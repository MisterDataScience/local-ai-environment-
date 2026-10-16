"""Native approval acceptance checks; synthetic inference never executes tools."""
import http.client
import json
import re
import shlex
import socket
import threading
import time
from urllib.error import HTTPError

MARKER = 'Native approval check: '
CASES = ('direct-once', 'direct-once-again', 'direct-reject', 'worker-once', 'worker-reject')


def target(project, case):
    if case not in CASES:
        raise ValueError('Unknown approval scenario')
    # Repeat the exact same command to detect an approval accidentally saved.
    filename = 'direct-once' if case == 'direct-once-again' else case
    return project / ('approval-' + filename + '.txt')


def command(project, case):
    return "printf 'native-approval\\n' > " + shlex.quote(str(target(project, case)))


def tool(name, arguments, case):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': 'call-' + name + '-' + case, 'type': 'function',
         'function': {'name': name, 'arguments': json.dumps(arguments)}}]}


def completion(project, users, previous, content_text):
    """Return only model responses. Real OpenCode owns permissions and effects."""
    child = re.search(r'"task_id"\s*:\s*"approval-(worker-(?:once|reject))"', users)
    parent = re.findall(re.escape(MARKER) + r'(' + '|'.join(sorted(CASES, key=len, reverse=True)) + r')(?![a-z-])', users)
    if not child and not parent:
        return None
    case = child[1] if child else parent[-1]
    # New user turns retain earlier tool messages. Only this scenario's call IDs
    # can satisfy its completion; old approved commands cannot skip a fresh ask.
    previous = [m for m in previous if case in m.get('tool_call_id', '')]
    if child or case.startswith('direct-'):
        if not previous:
            return tool('bash', {'command': command(project, case),
                                 'description': 'Write the temporary native approval marker'}, case)
        return {'role': 'assistant', 'content': 'Approval scenario finished; native history records the outcome.'}
    if not previous:
        return tool('team_run', {'tasks': [{'id': 'approval-' + case, 'role': 'coder',
            'objective': MARKER + case,
            'constraints': 'Use bash once to write only ' + str(target(project, case)) +
                           '. Respect rejection; never retry or use an alternative tool.',
            'evidence': 'Temporary acceptance project.',
            'deliverable': 'Report the actual tool result, including rejection.'}]}, case)
    latest = content_text(previous[-1].get('content'))
    if '"cohort"' in latest:
        return tool('team_retire', {'ids': ['approval-' + case]}, case)
    if '"retired"' not in latest:
        raise RuntimeError('Unexpected native approval worker result: ' + latest)
    return {'role': 'assistant', 'content': 'Approval worker finished and retired.'}


class Events:
    """Keep the real authenticated SSE stream open during approval replies."""
    def __init__(self, headers, host='127.0.0.1', port=4096):
        self.connection = http.client.HTTPConnection(host, port, timeout=60)
        self.connection.connect()
        self.socket = self.connection.sock
        self.connection.request('GET', '/event', headers=headers)
        self.response = self.connection.getresponse()
        if self.response.status != 200 or 'text/event-stream' not in self.response.getheader('Content-Type', ''):
            self.close()
            raise RuntimeError('Authenticated native SSE is unavailable')
        self.condition = threading.Condition()
        self.events = []
        self.error = None
        self.closed = False
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        data = []
        try:
            while not self.closed:
                line = self.response.readline(65537)
                if not line:
                    raise RuntimeError('Native event stream closed')
                if len(line) > 65536:
                    raise RuntimeError('Native event exceeded the acceptance bound')
                if line.strip() == b'':
                    if data:
                        event = json.loads('\n'.join(data))
                        with self.condition:
                            self.events.append(event)
                            self.events = self.events[-512:]
                            self.condition.notify_all()
                        data = []
                elif line.startswith(b'data:'):
                    data.append(line[5:].decode().strip())
        except Exception as error:
            with self.condition:
                if not self.closed:
                    self.error = error
                self.condition.notify_all()

    def wait(self, kind, identifier, timeout=10):
        def matching():
            return next((e for e in self.events if e.get('type') == kind and
                         identifier in (e.get('properties', {}).get('id'),
                                        e.get('properties', {}).get('requestID'))), None)
        with self.condition:
            if not self.condition.wait_for(lambda: matching() or self.error, timeout):
                raise RuntimeError('Native SSE did not deliver ' + kind)
            if self.error:
                raise RuntimeError('Native SSE failed') from self.error
            return matching()['properties']

    def close(self):
        self.closed = True
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.response.close()
        self.connection.close()
        if hasattr(self, 'thread'):
            self.thread.join(2)
            if self.thread.is_alive():
                raise RuntimeError('Native SSE reader did not stop')


def expect_http(call, codes):
    try:
        call()
    except HTTPError as error:
        if error.code in codes:
            return
        raise
    raise RuntimeError('Native API unexpectedly accepted an unauthorised or stale reply')


def run_case(native, unauthorised, events, project, case, session):
    """Require a real pending ask before replying, then inspect native history."""
    path = target(project, case)
    if path.exists():
        raise RuntimeError('Approval marker already exists')
    before = {p['id'] for m in native('/session/' + session + '/message') for p in m['parts']
              if p.get('type') == 'tool'}
    done = threading.Event()
    outcome = {}
    def submit():
        try:
            outcome['answer'] = native('/session/' + session + '/message', {'agent': 'build', 'parts': [
                {'type': 'text', 'text': MARKER + case + '. Perform only the supplied temporary acceptance action.'}]})
        except Exception as error:
            outcome['error'] = error
        finally:
            done.set()
    thread = threading.Thread(target=submit, daemon=True)
    thread.start()
    owner = session
    try:
        deadline = time.monotonic() + 45
        pending = None
        while time.monotonic() < deadline:
            children = {s['id'] for s in native('/session/' + session + '/children')}
            matches = [p for p in native('/permission') if p.get('sessionID') in {session, *children}]
            if matches:
                if len(matches) != 1:
                    raise RuntimeError('Unexpected extra native approval requests')
                pending = matches[0]
                break
            if done.wait(0.05):
                raise RuntimeError('Native command finished without its required approval: ' + str(outcome))
        if not pending:
            raise RuntimeError('Native approval did not become pending')
        owner = pending['sessionID']
        if pending.get('permission') != 'bash' or (owner != session) != case.startswith('worker-'):
            raise RuntimeError('Approval belongs to the wrong tool or session')
        if (pending.get('metadata', {}).get('command') != command(project, case) or
                not pending.get('patterns')):
            raise RuntimeError('Native approval does not describe the exact command')
        identifier = pending['id']
        asked = events.wait('permission.asked', identifier)
        if asked.get('sessionID') != owner or asked.get('permission') != 'bash':
            raise RuntimeError('Native SSE approval ownership mismatch')
        if path.exists() or done.wait(0.3):
            raise RuntimeError('Native command ran before the approval reply')
        for auth in ('missing', 'wrong'):
            expect_http(lambda: unauthorised('/permission', auth=auth), {401, 403})
            expect_http(lambda: unauthorised('/permission/' + identifier + '/reply',
                                            {'reply': 'once'}, auth=auth), {401, 403})
        if path.exists() or not any(p['id'] == identifier for p in native('/permission')):
            raise RuntimeError('Unauthorised request changed the pending approval')
        reply = 'reject' if case.endswith('reject') else 'once'
        native('/permission/' + identifier + '/reply', {'reply': reply})
        replied = events.wait('permission.replied', identifier)
        if replied.get('sessionID') != owner or replied.get('reply') != reply:
            raise RuntimeError('Native SSE reply ownership/result mismatch')
        if not done.wait(45):
            raise RuntimeError('Native parent did not finish after replying')
        if 'error' in outcome or outcome.get('answer', {}).get('info', {}).get('error'):
            raise RuntimeError('Native approval scenario failed: ' + str(outcome))
        tools = [p for m in native('/session/' + owner + '/message') for p in m['parts']
                 if p.get('type') == 'tool' and p.get('id') not in before and p.get('tool') == 'bash' and
                 p.get('state', {}).get('input', {}).get('command') == command(project, case)]
        expected = 'error' if reply == 'reject' else 'completed'
        if len(tools) != 1 or tools[0]['state']['status'] != expected:
            raise RuntimeError('Native tool outcome does not match the approval: ' + str(tools))
        if reply == 'reject':
            if path.exists() or 'reject' not in str(tools[0]['state'].get('error', '')).lower():
                raise RuntimeError('Denied command executed or lacks native rejection evidence')
        elif not path.is_file() or path.read_text() != 'native-approval\n':
            raise RuntimeError('Approved native command did not produce its expected effect')
        if any(p['id'] == identifier for p in native('/permission')):
            raise RuntimeError('Replied permission remains pending')
        expect_http(lambda: native('/permission/' + identifier + '/reply', {'reply': 'once'}), {404})
        if case.startswith('worker-'):
            parents = [p for m in native('/session/' + session + '/message') for p in m['parts']
                       if p.get('type') == 'tool']
            retired = next((p for p in parents if p.get('tool') == 'team_retire' and
                            p.get('state', {}).get('status') == 'completed'), None)
            if not retired or 'approval-' + case not in json.loads(retired['state']['output'])['retired']:
                raise RuntimeError('Approval worker did not retire')
        return identifier
    finally:
        if not done.is_set():
            for identifier in {session, owner}:
                try:
                    native('/session/' + identifier + '/abort', {})
                except Exception:
                    pass
        thread.join(5)
        if thread.is_alive():
            raise RuntimeError('Native approval request did not stop after abort')


def check(native, unauthorised, headers, project):
    events = Events(headers)
    try:
        direct = native('/session', {'title': 'Native direct approvals'})['id']
        identifiers = set()
        for case in CASES:
            if case == 'direct-once-again':
                target(project, 'direct-once').unlink()
            session = direct if case.startswith('direct-') else native('/session', {'title': case})['id']
            identifier = run_case(native, unauthorised, events, project, case, session)
            if identifier in identifiers:
                raise RuntimeError('Native approval request ID was reused')
            identifiers.add(identifier)
    finally:
        events.close()
    print('Real OpenCode: direct and delegated approval/rejection, once-only scope, authentication and SSE verified.')
