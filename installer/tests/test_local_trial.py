"""LOCAL AI local-trial release contract.

These are host-independent checks. The Mac must still run native acceptance.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from turnkey_install import acceptance_summary, write_receipt
from model_engine import Engine


class LocalTrialTests(unittest.TestCase):
    @staticmethod
    def configuration():
        return {
            'install_profile': 'local-trial',
            'text_models': {
                'local-ai': {'name': 'Small local model', 'model': 'qwen3:14b',
                             'keep_alive_seconds': 120, 'num_ctx': 8192,
                             'thinking': False},
                'local-ai-captain': {'name': 'Shared Captain', 'model': 'native-test',
                                     'backend': 'llama', 'keep_alive_seconds': 120,
                                     'num_ctx': 8192, 'thinking': False},
            },
            'captain': {'enabled': True, 'model_id': 'local-ai-captain',
                        'provider': 'llama'}
        }

    def test_text_and_native_captain_are_still_required(self):
        config = self.configuration()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [
                {'name': 'text', 'status': 'passed'},
                {'name': 'text-local-ai', 'status': 'passed'},
                {'name': 'text-local-ai-captain', 'status': 'passed'},
                {'name': 'native-captain-team', 'status': 'passed'},
                {'name': 'image', 'status': 'not_run'},
                {'name': 'video', 'status': 'not_run'},
            ]
            path = root / 'acceptance-report.json'
            path.write_text(json.dumps({'checks': rows}))
            self.assertIn('native-captain-team',
                          acceptance_summary(root, config)['passed_checks'])
            config['install_profile'] = 'full'
            with self.assertRaises(RuntimeError):
                acceptance_summary(root, config)
            config['install_profile'] = 'local-trial'
            rows[3]['status'] = 'not_run'
            path.write_text(json.dumps({'checks': rows}))
            with self.assertRaises(RuntimeError):
                acceptance_summary(root, config)

    def test_receipt_discloses_deferred_integrations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = write_receipt(root, self.configuration(),
                                    {'passed_checks': ['text', 'native-captain-team']},
                                    {'webui_health': 'passed'},
                                    require_integrations=False)
            self.assertEqual(receipt['profile'], 'local-trial')
            self.assertEqual(receipt['encrypted_workspace']['status'],
                             'not_configured')
            self.assertEqual(receipt['integration_acceptance']['vpn_web'],
                             'not_configured')
            self.assertEqual(receipt['integration_acceptance']['private_remote_captain'],
                             'not_configured')

    def test_media_commands_refused_before_inference(self):
        engine = object.__new__(Engine)
        engine.config = {'install_profile': 'local-trial'}
        engine.text_models = {'local-ai': self.configuration()['text_models']['local-ai']}
        engine.pause_commons = lambda *_: None
        for command in ('/image a tree', '/video a tree', '/speak hello',
                        '/search trees', '/read https://example.com trees'):
            with self.subTest(command=command):
                with self.assertRaisesRegex(ValueError, 'text requests only'):
                    engine.submit({'model': 'local-ai',
                                   'messages': [{'role': 'user', 'content': command}]})


if __name__ == '__main__':
    unittest.main()
