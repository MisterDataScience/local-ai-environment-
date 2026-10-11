import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'payload'))
import workspace_setup as setup
import account_tools
import common


class WorkspaceSetupTests(unittest.TestCase):
    def test_configuration_is_atomic_private_and_contains_no_password(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'control').mkdir()
            setup.save_config(root, {'vault': {'enabled': True, 'manual_unlock': True, 'save_password': False}})
            p = root / 'control/config.json'
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertTrue(json.loads(p.read_text())['vault']['manual_unlock'])
            self.assertEqual(len(list(p.parent.iterdir())), 1)

    def test_registration_rejects_plain_folder_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                setup.register(Path(d), d)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_github_token_permissions_and_connection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'secrets').mkdir()
            token = root / 'secrets/github-token'
            token.write_text('test-token')
            token.chmod(0o644)
            with self.assertRaises(ValueError):
                account_tools.connection(root)
            token.chmod(0o600)
            result = account_tools.connection(root)
            self.assertEqual(result['type'], 'mcp')
            self.assertEqual(result['key'], 'test-token')
            self.assertEqual(result['url'], 'https://api.githubcopilot.com/mcp/')
            self.assertNotIn('delete_file', result['headers']['X-MCP-Tools'])

    def test_workflow_and_existing_tool_connections_coexist(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = {'api_key': 'local-key', 'webui_secret': 'web-key', 'web': {'enabled': True},
                      'vault': {'enabled': True}, 'account_tools': {'github': True}}
            with patch.object(account_tools, 'connection', return_value={'type': 'mcp', 'url': account_tools.URL,
                    'info': {'id': 'local-ai-github', 'name': 'GitHub', 'description': 'Test integration'}}):
                env = common.webui_environment(root, config)
            servers = json.loads(env['TOOL_SERVER_CONNECTIONS'])
            self.assertEqual(len(servers), 4)
            self.assertIn('workspace/openapi.json', [s.get('path') for s in servers])
            self.assertIn('files/openapi.json', [s.get('path') for s in servers])
            self.assertEqual(json.loads(env['DEFAULT_MODEL_PARAMS'])['tool_approval_mode'], 'ask')

    def test_existing_cryptomator_is_verified_and_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            app = root / 'tools/Cryptomator.app'
            app.mkdir(parents=True)
            with patch.object(setup.Path, 'home', return_value=root / 'home'), patch.object(setup.subprocess, 'run'):
                from unittest.mock import Mock
                download, run = Mock(), Mock()
                result = setup.install_cryptomator(root, download, run)
            self.assertEqual(result, app)
            download.assert_not_called()
            self.assertEqual(run.call_count, 2)

if __name__ == '__main__':
    unittest.main()

