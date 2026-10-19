"""Test the acceptance harness's failure detection, not OpenCode itself."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError

import native_approvals as approvals


def text(value):
    return value if isinstance(value, str) else ''


class Fixture:
    """Deliberate test double; its effects are never native acceptance evidence."""
    def __init__(self, project, case, fault=None):
        self.project, self.case, self.fault = project, case, fault
        self.owner = 'ses_child' if case.startswith('worker') else 'ses_parent'
        self.pending = {'id': 'per_test', 'sessionID': self.owner, 'permission': 'bash',
                        'patterns': ['printf'], 'metadata': {'command': approvals.command(project, case)}}
        self.active = False
        self.finished = threading.Event()
        self.reply = None
        self.auth_attempts = []

    def native(self, path, body=None):
        if path.endswith('/abort'):
            self.finished.set()
            return True
        if path == '/session/ses_parent/message' and body:
            if self.fault == 'early-effect':
                approvals.target(self.project, self.case).write_text('native-approval\n')
            self.active = True
            if not self.finished.wait(3):
                raise RuntimeError('Fixture timed out')
            return {'info': {}}
        if path.endswith('/children'):
            return [{'id': 'ses_child'}] if self.owner == 'ses_child' else []
        if path == '/permission':
            return [self.pending] if self.active and not self.finished.is_set() else []
        if path == '/permission/per_test/reply':
            if self.finished.is_set():
                raise HTTPError(path, 404, 'stale', {}, None)
            self.reply = body['reply']
            if ((self.reply == 'once' and self.fault != 'missing-effect') or self.fault == 'denied-effect'):
                approvals.target(self.project, self.case).write_text('native-approval\n')
            self.finished.set()
            return True
        if path.endswith('/message'):
            if not self.active:
                return []
            if path == '/session/ses_parent/message' and self.owner == 'ses_child':
                return [{'parts': [{'type': 'tool', 'tool': 'team_retire', 'state': {
                    'status': 'completed', 'output': json.dumps({'retired': ['approval-' + self.case]})}}]}]
            state = {'input': {'command': approvals.command(self.project, self.case)},
                     'status': 'error' if self.reply == 'reject' else 'completed',
                     'error': 'The user rejected permission'}
            parts = [{'id': 'part-' + self.case, 'type': 'tool', 'tool': 'bash', 'state': state}]
            if self.fault == 'duplicate-action':
                parts.append(dict(parts[0]))
            return [{'parts': parts}]
        raise AssertionError('Unexpected fixture endpoint ' + path)

    def unauthorised(self, path, body=None, auth=None):
        self.auth_attempts.append((path, auth))
        if self.fault == 'unauthorised-accepted':
            return True
        raise HTTPError(path, 401, 'auth required', {}, None)

    def wait(self, kind, identifier):
        return dict(self.pending, requestID=identifier, reply=self.reply)


class ApprovalHarnessTests(unittest.TestCase):
    def test_direct_and_worker_allow_reject_and_once_again_oracles(self):
        for case in approvals.CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                fixture = Fixture(Path(folder), case)
                self.assertEqual(approvals.run_case(fixture.native, fixture.unauthorised, fixture,
                                                   Path(folder), case, 'ses_parent'), 'per_test')
                self.assertEqual(len(fixture.auth_attempts), 4)

    def test_faults_fail_instead_of_claiming_approval_succeeded(self):
        for fault, case, message in (
                ('early-effect', 'direct-once', 'before the approval'),
                ('missing-effect', 'direct-once', 'expected effect'),
                ('denied-effect', 'direct-reject', 'Denied command executed'),
                ('unauthorised-accepted', 'direct-once', 'unexpectedly accepted'),
                ('duplicate-action', 'worker-once', 'tool outcome')):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                fixture = Fixture(Path(folder), case, fault)
                with self.assertRaisesRegex(RuntimeError, message):
                    approvals.run_case(fixture.native, fixture.unauthorised, fixture,
                                       Path(folder), case, 'ses_parent')
                self.assertTrue(fixture.finished.is_set())

    def test_wrong_native_session_or_sse_owner_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            fixture = Fixture(project, 'worker-once')
            fixture.owner = 'ses_parent'
            fixture.pending['sessionID'] = 'ses_parent'
            with self.assertRaisesRegex(RuntimeError, 'wrong tool or session'):
                approvals.run_case(fixture.native, fixture.unauthorised, fixture,
                                   project, 'worker-once', 'ses_parent')
            fixture = Fixture(project, 'direct-once')
            class WrongEvents:
                def wait(self, *args):
                    return dict(fixture.pending, sessionID='ses_unrelated')
            with self.assertRaisesRegex(RuntimeError, 'ownership mismatch'):
                approvals.run_case(fixture.native, fixture.unauthorised, WrongEvents(),
                                   project, 'direct-once', 'ses_parent')

    def test_synthetic_turns_do_not_reuse_old_approvals(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            self.assertEqual(approvals.command(project, 'direct-once'), approvals.command(project, 'direct-once-again'))
            users = approvals.MARKER + 'direct-once.\n' + approvals.MARKER + 'direct-once-again.'
            previous = [{'tool_call_id': 'call-bash-direct-once', 'content': 'prior success'}]
            message = approvals.completion(project, users, previous, text)
            self.assertEqual(message['tool_calls'][0]['id'], 'call-bash-direct-once-again')
            args = json.loads(message['tool_calls'][0]['function']['arguments'])
            self.assertIn(str(approvals.target(project, 'direct-once-again')), args['command'])
            self.assertIsNone(approvals.completion(project, 'ordinary request', [], text))

    def test_synthetic_worker_dispatch_and_retirement_messages(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            case = 'worker-reject'
            users = approvals.MARKER + case + '.'
            result = approvals.completion(project, users, [], text)
            dispatch = result['tool_calls'][0]
            task = json.loads(dispatch['function']['arguments'])['tasks'][0]
            worker = approvals.completion(project, json.dumps({'task_id': task['id']}), [], text)
            self.assertEqual(worker['tool_calls'][0]['function']['name'], 'bash')
            after = [{'tool_call_id': dispatch['id'], 'content': '{"cohort":1}'}]
            result = approvals.completion(project, users, after, text)
            self.assertEqual(result['tool_calls'][0]['function']['name'], 'team_retire')
            after.append({'tool_call_id': result['tool_calls'][0]['id'], 'content': '{"retired":[]}'} )
            self.assertNotIn('tool_calls', approvals.completion(project, users, after, text))

    def test_real_http_sse_decoding_and_bounded_reader_shutdown(self):
        release = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                if self.headers.get('Authorization') != 'Basic fixture':
                    self.send_error(401)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for kind in ('asked', 'replied'):
                    data = {'type': 'permission.' + kind,
                            'properties': {'id': 'per_fixture', 'sessionID': 'ses_fixture'}}
                    self.wfile.write(('data: ' + json.dumps(data) + '\n\n').encode())
                    self.wfile.flush()
                release.wait(3)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        events = None
        try:
            events = approvals.Events({'Authorization': 'Basic fixture'}, port=server.server_port)
            for kind in ('asked', 'replied'):
                self.assertEqual(events.wait('permission.' + kind, 'per_fixture')['sessionID'], 'ses_fixture')
            with self.assertRaisesRegex(RuntimeError, 'did not deliver'):
                events.wait('permission.asked', 'per_other', timeout=0.01)
            events.close()
            self.assertFalse(events.thread.is_alive())
            events = None
        finally:
            if events:
                events.close()
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
