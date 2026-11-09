"""Probe protocol tests use simulated inference, not native-model qualification."""
import contextlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
import captain_conversation_check


class NativeConversationTests(unittest.TestCase):
    def module(self):
        return captain_conversation_check

    def probe_fixture(self, root):
            control = root / 'control'
            control.mkdir()
            (control / 'config.json').write_text(json.dumps({'captain': {'model_id': 'local-ai-captain'}}))
            (control / 'captain-ui-auth.json').write_text(json.dumps({'username': 'opencode', 'password': 'PRIVATE-PROBE-SECRET'}))
            (root / 'work-agent/projects/captain-default').mkdir(parents=True)

    def fake_native(self, *, extra_reply=False, old_budget=False, fail_compaction=False):
            calls, messages, summaries, pending = [], [], [], []
            def open_request(request, timeout):
                path = urlsplit(request.full_url).path
                body = json.loads(request.data) if request.data else None
                calls.append((path, body))
                if path == '/config':
                    value = {'provider': {'local-ai-gateway': {'models': {'local-ai-captain': {'limit':
                        {'context': 16384, 'output': 8192 if old_budget else 4096, 'input': 12288}}}}},
                        'compaction': {'reserved': 2048 if old_budget else 512}}
                elif path == '/session':
                    self.assertEqual(body['permission'], [{'permission': '*', 'pattern': '*', 'action': 'deny'}])
                    value = {'id': 'ses_probe'}
                elif path == '/session/ses_probe/message' and body is not None:
                    if body.get('noReply'):
                        pending.append(True)
                        value = {'info': {'id': 'queued-user', 'role': 'user'}, 'parts': body['parts']}
                        messages.append(value)
                    else:
                        value = {'info': {'id': 'reply', 'role': 'assistant', 'agent': 'plan', 'finish': 'stop'},
                                 'parts': [{'type': 'text', 'text': 'READY'}]}
                        messages.append(value)
                elif path == '/session/ses_probe/summarize':
                    self.assertTrue(body['auto'])
                    if fail_compaction:
                        raise RuntimeError('Native compaction failed')
                    summary = {'info': {'id': 'summary' + str(len(summaries)), 'role': 'assistant', 'agent': 'compaction',
                               'summary': True, 'finish': 'stop'}, 'parts': [{'type': 'text', 'text': 'Completed: READY. Next: none.'}]}
                    summaries.append(summary)
                    messages.append(summary)
                    if pending:
                        pending.clear()
                        messages.append({'info': {'id': 'queued-answer', 'role': 'assistant', 'agent': 'plan', 'finish': 'stop'},
                                         'parts': [{'type': 'text', 'text': 'DONE'}]})
                    if extra_reply:
                        messages.append({'info': {'id': 'extra', 'role': 'assistant', 'agent': 'plan', 'finish': 'stop'},
                                         'parts': [{'type': 'text', 'text': 'More unwanted suggestions.'}]})
                    value = True
                elif path == '/session/ses_probe/message':
                    value = messages
                elif path == '/session/ses_probe/abort':
                    value = True
                else:
                    raise AssertionError('Unexpected native operation: ' + path)
                return contextlib.closing(__import__('io').BytesIO(json.dumps(value).encode()))
            opener = type('Opener', (), {'open': staticmethod(open_request)})()
            return opener, calls

    def test_native_probe_checks_completed_and_unfinished_requests(self):
            module = self.module()
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.probe_fixture(root)
                opener, calls = self.fake_native()
                with patch.object(module, 'build_opener', return_value=opener):
                    report = module.verify_native(root, startup_timeout=0)
                self.assertEqual(report['status'], 'passed')
                self.assertEqual(report['ordinary_reply_count'], 2)
                self.assertEqual(report['summary_count'], 4)
                self.assertEqual(sum(path.endswith('/summarize') for path, _ in calls), 4)
                self.assertTrue(report['checks']['unfinished_request_resumes'])
                self.assertTrue(report['checks']['resumed_reply_stays_stopped'])
                saved = (root / 'logs/native-acceptance/conversation-repair-probe.json').read_text()
                self.assertNotIn('PRIVATE-PROBE-SECRET', saved)
                self.assertIn('not full installation acceptance', report['scope'])

    def test_native_probe_fails_extra_answers_and_aborts_only_its_own_session(self):
            module = self.module()
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.probe_fixture(root)
                opener, calls = self.fake_native(extra_reply=True)
                with patch.object(module, 'build_opener', return_value=opener):
                    report = module.verify_native(root, startup_timeout=0)
                self.assertEqual(report['status'], 'failed')
                self.assertIn('extra answer', report['issue'])
                self.assertEqual(calls[-1][0], '/session/ses_probe/abort')

    def test_native_probe_rejects_old_budget_without_inference(self):
            module = self.module()
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.probe_fixture(root)
                opener, calls = self.fake_native(old_budget=True)
                with patch.object(module, 'build_opener', return_value=opener):
                    report = module.verify_native(root, startup_timeout=0)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(calls, [('/config', None)])

    def test_failed_compaction_cannot_be_reported_as_a_pass(self):
            module = self.module()
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.probe_fixture(root)
                opener, calls = self.fake_native(fail_compaction=True)
                with patch.object(module, 'build_opener', return_value=opener):
                    report = module.verify_native(root, startup_timeout=0)
                self.assertEqual(report['status'], 'failed')
                self.assertNotIn('completed_chat_stays_stopped_1', report['checks'])
                self.assertEqual(calls[-1][0], '/session/ses_probe/abort')

    def test_installer_supplied_native_client_uses_no_saved_ui_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            opener, calls = self.fake_native()
            def native(path, body=None, *, timeout=180):
                request = Request('http://127.0.0.1:4096' + path,
                                  data=json.dumps(body).encode() if body is not None else None)
                with opener.open(request, timeout=timeout) as response:
                    return json.load(response)
            report = captain_conversation_check.verify_native(root, native=native,
                model_id='local-ai-captain', startup_timeout=0)
            self.assertEqual(report['status'], 'passed')
            self.assertFalse((root / 'control/captain-ui-auth.json').exists())
            self.assertTrue(report['checks']['unfinished_request_resumes'])


if __name__ == '__main__':
    unittest.main()
