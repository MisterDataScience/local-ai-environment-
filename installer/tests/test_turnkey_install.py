"""Turnkey Captain readiness and credential regressions without pretending to run macOS."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
from managed_captain import credentials, READY_NAME
from turnkey_install import BASE_CHECKS, acceptance_summary, await_background, write_receipt


class TurnkeyCaptainTests(unittest.TestCase):
    def config(self):
        return {'api_key': 'test-secret',
                'text_models': {
                    'local-ai': {'name': 'Small', 'model': 'qwen3:4b',
                                 'num_ctx': 8192, 'keep_alive_seconds': 120, 'thinking': False},
                    'local-ai-captain': {'name': 'Captain', 'model': 'MiniCPM-V-4.7-35B-A3B',
                                         'backend': 'llama', 'num_ctx': 16384,
                                         'keep_alive_seconds': 120, 'thinking': False}},
                'captain': {'enabled': True, 'provider': 'llama', 'model_id': 'local-ai-captain'}}

    def native_report(self):
        names = list(BASE_CHECKS) + ['text-local-ai', 'text-local-ai-captain', 'native-captain-team']
        return {'checks': [{'name': name, 'status': 'passed'} for name in names] +
                          [{'name': 'mic', 'status': 'not_run'}]}

    def test_private_auth_is_stable_and_rejects_unsafe_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'control').mkdir()
            first = credentials(root)
            self.assertEqual(first, credentials(root))
            self.assertEqual(first['username'], 'opencode')
            path = root / 'control/captain-ui-auth.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, 'private'):
                credentials(root)
            path.unlink()
            path.symlink_to(root / 'unrelated')
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                credentials(root)

    def test_no_success_receipt_without_real_native_captain_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = self.native_report()
            report['checks'] = [item for item in report['checks'] if item['name'] != 'native-captain-team']
            (root / 'acceptance-report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(RuntimeError, 'native-captain-team'):
                acceptance_summary(root, self.config())
            report = self.native_report()
            (root / 'acceptance-report.json').write_text(json.dumps(report))
            summary = acceptance_summary(root, self.config())
            self.assertIn('native-captain-team', summary['passed_checks'])
            self.assertIn('mic', summary['pending_checks'])

    def test_live_readiness_checks_gateway_and_authenticated_agent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'control').mkdir()
            (root / 'control' / READY_NAME).write_text('{}')
            def http(url, **kwargs):
                if url.endswith('/health'):
                    return {'status': True}
                if url.endswith('/v1/models'):
                    return {'data': [{'id': 'local-ai-captain'}, {'id': 'local-ai'}]}
                return {'mode': 'max', 'transitioning': False, 'error': None}
            with patch('turnkey_install.http', side_effect=http), \
                 patch('turnkey_install.agent_status', return_value={'captain_agent_endpoint': 'passed'}):
                result = await_background(root, self.config(), timeout=2)
            self.assertEqual(result['captain_visible'], 'passed')
            self.assertEqual(result['mode'], 'max')
            self.assertEqual(result['captain_native_agents']['captain_agent_endpoint'], 'passed')

    def test_install_receipt_never_calls_deferred_features_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record = write_receipt(root, self.config(), {'passed_checks': ['native-captain-team']},
                                   {'captain_visible': 'passed'})
            self.assertEqual(record['profile'], 'minicpm-captain')
            self.assertIn('first_login_after_reboot', record['pending_physical_acceptance'])
            self.assertIn('vpn_browser', record['deferred_permissions_and_accounts'])
            self.assertIn('remote_captain_ui', record['deferred_permissions_and_accounts'])
            self.assertIn('captain_access_from_another_tailnet_device', record['pending_physical_acceptance'])
            self.assertNotEqual(record['status'], 'fully_verified')
            self.assertEqual(json.loads((root / 'captain-install-readiness.json').read_text()), record)

    def test_single_installer_selects_captain_and_runtime_contains_managed_agent(self):
        script = (ROOT / 'Install Local AI.command').read_text()
        self.assertIn('--minicpm-captain "$@"', script)
        runtime = (ROOT / 'runtime.py').read_text()
        self.assertIn("'--managed'", runtime)


if __name__ == '__main__':
    unittest.main()
