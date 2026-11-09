"""Saved-state scope, redaction and isolated retries using a real SQLite fixture."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import acceptance_diagnostics as diagnostics


class AcceptanceDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        control = self.root / 'control'
        control.mkdir()
        self.secret = 'PRIVATE_GATEWAY_KEY_9971'
        (control / 'config.json').write_text(json.dumps({'api_key': self.secret,
            'captain': {'enabled': True, 'provider': 'llama', 'model_id': 'local'},
            'text_models': {'local': {'model': 'MiniCPM', 'backend': 'llama', 'thinking': True, 'num_ctx': 16384}}}))
        self.progress = self.root / 'acceptance-report.json'
        self.progress.write_text(json.dumps({'checks': [{'name': 'text-local', 'status': 'passed'}]}))
        self.db = self.root / 'work-agent/state/data/opencode/opencode.db'
        self.db.parent.mkdir(parents=True)
        with sqlite3.connect(self.db) as db:
            db.executescript('CREATE TABLE session(id TEXT,parent_id TEXT,title TEXT,time_created INTEGER);'
                'CREATE TABLE message(id TEXT,session_id TEXT,time_created INTEGER,data TEXT);'
                'CREATE TABLE part(id TEXT,session_id TEXT,message_id TEXT,data TEXT);')
            db.executemany('INSERT INTO session VALUES(?,?,?,?)', [
                ('old', None, diagnostics.TITLE, 100), ('parent', None, diagnostics.TITLE, 200),
                ('child', 'parent', 'file-check', 201), ('private', None, 'Unrelated owner session', 300)])
            db.executemany('INSERT INTO message VALUES(?,?,?,?)', [
                ('user', 'parent', 200, json.dumps({'role': 'user'})),
                ('assistant', 'parent', 201, json.dumps({'role': 'assistant', 'agent': 'plan'})),
                ('worker', 'child', 202, json.dumps({'role': 'assistant', 'agent': 'captain-reviewer'})),
                ('private-msg', 'private', 301, json.dumps({'role': 'assistant', 'private': 'PRIVATE_OTHER_SESSION'}))])
            db.executemany('INSERT INTO part VALUES(?,?,?,?)', [
                ('call', 'parent', 'assistant', json.dumps({'type': 'tool', 'tool': 'team_run', 'callID': 'native-call',
                    'state': {'status': 'error', 'input': {'tasks': [], 'api_key': self.secret},
                              'error': 'Captain: invalid task ' + self.secret}})),
                ('thought', 'child', 'worker', json.dumps({'type': 'reasoning', 'text': 'INTERNAL_REASONING_NOT_NEEDED'})),
                ('file', 'child', 'worker', json.dumps({'type': 'tool', 'tool': 'read', 'callID': 'native-read',
                    'state': {'status': 'error', 'error': 'File inspection failed'}}))])
        self.worker_report = self.root / 'work-agent/captain-acceptance/.local-ai-team/report.json'
        self.worker_report.parent.mkdir(parents=True)
        self.worker_report.write_text(json.dumps({'output': 'Worker failed', 'native_tools': []}))
        key = hashlib.sha256(b'parent\0user').hexdigest()
        ledger = {'turns': {key: {'tasks': [{'id': 'file-check', 'role': 'reviewer', 'status': 'failed',
                    'error': 'Worker refused', 'report': str(self.worker_report)}]},
                  'unrelated': {'tasks': [{'error': 'PRIVATE_OTHER_TURN'}]}}}
        (self.root / 'work-agent/state/captain.json').write_text(json.dumps(ledger))
        logs = self.db.parent / 'log'
        logs.mkdir()
        (logs / 'opencode.log').write_text('run=other message=PRIVATE_OTHER_LOG\n'
            'run=acceptance message=created id=parent\nrun=acceptance message=failed key=' + self.secret + '\n')

    def test_complete_snapshot_scopes_latest_acceptance_and_preserves_errors_readonly(self):
        before = self.db.read_bytes()
        report = diagnostics.collect(self.root)
        text = json.dumps(report)
        self.assertEqual(report['session_id'], 'parent')
        self.assertEqual([s['id'] for s in report['sessions']], ['parent', 'child'])
        self.assertEqual(report['summary']['parent_tools']['team_run'], {'error': 1})
        self.assertIn('Captain: invalid task', report['summary']['errors'][0]['error'])
        self.assertEqual(report['worker_reports'][0]['report']['output'], 'Worker failed')
        self.assertNotIn(self.secret, text)
        for excluded in ('PRIVATE_OTHER_SESSION', 'PRIVATE_OTHER_TURN', 'PRIVATE_OTHER_LOG', 'INTERNAL_REASONING_NOT_NEEDED'):
            self.assertNotIn(excluded, text)
        self.assertFalse(report['new_inference_requested'])
        self.assertEqual(self.db.read_bytes(), before)

    def test_retry_window_cannot_report_an_older_session_as_fresh(self):
        report = diagnostics.collect(self.root, since_ms=500)
        self.assertEqual(report['summary']['status'], 'no_matching_captain_session')
        self.assertEqual(report['sessions'], [])
        self.assertEqual(report['captain_turns'], {})

    def test_worker_report_paths_cannot_expand_the_snapshot_scope(self):
        ledger = self.root / 'work-agent/state/captain.json'
        data = json.loads(ledger.read_text())
        next(iter(data['turns'].values()))['tasks'][0]['report'] = str(self.root / 'control/config.json')
        ledger.write_text(json.dumps(data))
        report = diagnostics.collect(self.root)
        self.assertEqual(report['worker_reports'], [])
        self.assertTrue(any('outside' in e for e in report['collection_errors']))

    def test_private_atomic_output_preserves_unrelated_existing_files(self):
        report = diagnostics.collect(self.root)
        output = self.root / 'diagnostic.json'
        diagnostics.save(output, report)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(output.read_text())['stage'], 'captain')
        diagnostics.save(output, report)
        output.write_text('{"owner_file":true}')
        with self.assertRaisesRegex(ValueError, 'not a Local AI diagnostic'):
            diagnostics.save(output, report)
        self.assertEqual(output.read_text(), '{"owner_file":true}')

    def test_missing_database_still_produces_a_usable_snapshot(self):
        self.db.unlink()
        report = diagnostics.collect(self.root)
        self.assertEqual(report['summary']['status'], 'no_matching_captain_session')
        self.assertEqual(report['recorded_core_checks'][0]['status'], 'passed')

    def test_standalone_cli_collects_existing_failure_without_runtime_imports(self):
        output = self.root / 'captain-diagnostic.json'
        result = subprocess.run([sys.executable, '-I', diagnostics.__file__, '--root', str(self.root),
                                 '--output', str(output)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary['parent_tools']['team_run'], {'error': 1})
        self.assertIn('Captain: invalid task', summary['first_error']['error'])
        self.assertNotIn(self.secret, result.stdout + output.read_text())
        self.assertFalse(json.loads(output.read_text())['new_inference_requested'])

    def test_isolated_retry_calls_only_captain_and_never_writes_readiness_receipts(self):
        calls = []
        @contextmanager
        def lock(root):
            calls.append('lock')
            yield
            calls.append('unlock')
        @contextmanager
        def services(root, features):
            self.assertEqual(features, ('core',))
            calls.append('services-start')
            try:
                yield {'api_key': self.secret}
            finally:
                calls.append('services-stop')
        verify = Mock(return_value=[{'name': 'native-captain-team', 'status': 'passed'}])
        modules = {'feature_state': types.SimpleNamespace(installation_lock=lock),
            'feature_install': types.SimpleNamespace(ensure_stopped=lambda root: calls.append('preflight')),
            'feature_checks': types.SimpleNamespace(services=services),
            'captain_check': types.SimpleNamespace(verify=verify)}
        original = self.progress.read_bytes()
        previous_path = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous_path))
        with patch.dict(sys.modules, modules):
            report = diagnostics.retry_captain(self.root)
        self.assertEqual(report['probe']['status'], 'passed')
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(calls, ['lock', 'preflight', 'services-start', 'services-stop', 'unlock'])
        self.assertEqual(self.progress.read_bytes(), original)
        self.assertFalse((self.root / 'accepted-core-fingerprint.txt').exists())
        self.assertFalse(report['full_installation_acceptance_performed'])

    def test_failed_retry_keeps_primary_failure_and_cleans_up(self):
        @contextmanager
        def services(root, features):
            try:
                yield {}
            finally:
                raise RuntimeError('Cleanup failed')
        @contextmanager
        def lock(root):
            yield
        modules = {'feature_state': types.SimpleNamespace(installation_lock=lock),
            'feature_install': types.SimpleNamespace(ensure_stopped=lambda root: None),
            'feature_checks': types.SimpleNamespace(services=services),
            'captain_check': types.SimpleNamespace(verify=Mock(side_effect=RuntimeError('Primary failure ' + self.secret)))}
        previous_path = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous_path))
        with patch.dict(sys.modules, modules):
            report = diagnostics.retry_captain(self.root)
        self.assertEqual(report['probe']['status'], 'failed')
        self.assertIn('Primary failure', report['probe']['error'])
        self.assertEqual(report['probe']['cleanup_errors'], ['Cleanup failed'])
        self.assertNotIn(self.secret, json.dumps(report))


if __name__ == '__main__':
    unittest.main()
