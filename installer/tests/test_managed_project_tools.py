"""Real MCP subprocess startup and file boundaries for the persistent Captain."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE), str(SOURCE / 'payload')]
from file_transfer import MANAGED_PROJECT_ID, project_path, transfer_local
from file_workflows import publish_project, active_project
from vault_transfer import transfer_vault


class ManagedProjectToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'work-agent/projects' / MANAGED_PROJECT_ID
        self.project.mkdir(parents=True)

    def launch(self, script, project=None):
        project = project or self.project
        command = [sys.executable, str(SOURCE / script), '--project', str(project)]
        if script != 'pdf_mcp.py':
            command += ['--root', str(self.root)]
        requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                     'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                                'clientInfo': {'name': 'regression', 'version': '1'}}},
                    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(SOURCE), str(SOURCE / 'payload')]))
        return subprocess.run(command, input=''.join(json.dumps(row) + '\n' for row in requests),
                              text=True, capture_output=True, timeout=10, env=env)

    def test_all_three_real_mcp_servers_initialize_and_discover_tools_in_managed_project(self):
        for script, tool in [('pdf_mcp.py', 'read_pdf'), ('transfer_mcp.py', 'transfer_file'),
                             ('vision_mcp.py', 'inspect_image')]:
            with self.subTest(server=script):
                result = self.launch(script)
                self.assertEqual(result.returncode, 0, result.stderr)
                replies = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual([row['id'] for row in replies], [1, 2])
                self.assertIn('serverInfo', replies[0]['result'])
                self.assertIn(tool, [row['name'] for row in replies[1]['result']['tools']])

    def test_registration_and_real_local_transfer_preserve_the_existing_project(self):
        evidence = self.project / 'existing.txt'
        evidence.write_text('Existing work')
        uploads = self.root / 'web/browser-outputs'
        uploads.mkdir(parents=True)
        (uploads / 'input.txt').write_text('Imported text')
        publish_project(self.root, self.project, os.getpid())
        self.assertEqual(active_project(self.root), self.project)
        saved = transfer_local(self.root, MANAGED_PROJECT_ID, 'input.txt', 'browser-import')
        self.assertEqual(saved.read_text(), 'Imported text')
        self.assertEqual(evidence.read_text(), 'Existing work')
        with self.assertRaises(FileExistsError):
            transfer_local(self.root, MANAGED_PROJECT_ID, 'input.txt', 'browser-import')

    def test_vault_transfer_uses_the_same_managed_project_boundary(self):
        vault = self.root / 'mock-vault'
        for name in ('Inbox', 'Outputs'):
            (vault / name).mkdir(parents=True)
        (vault / 'Inbox/source.txt').write_text('Approved source')
        @contextmanager
        def mounted(_):
            fd = os.open(vault, os.O_RDONLY | os.O_DIRECTORY)
            try:
                yield fd
            finally:
                os.close(fd)
        with patch('vault_transfer.mounted_root', mounted):
            transfer_vault({}, self.root, MANAGED_PROJECT_ID, 'Inbox/source.txt', 'vault-import')
            self.assertEqual((self.project / 'Inbox/source.txt').read_text(), 'Approved source')
            transfer_vault({}, self.root, MANAGED_PROJECT_ID, 'Inbox/source.txt', 'vault-export')
            self.assertEqual((vault / 'Outputs/source.txt').read_text(), 'Approved source')
            with self.assertRaises(FileExistsError):
                transfer_vault({}, self.root, MANAGED_PROJECT_ID, 'Inbox/source.txt', 'vault-export')

    def test_arbitrary_names_traversal_and_symlinks_remain_rejected(self):
        for name in ('captain-other', '../captain-default', 'CAPTAIN-DEFAULT', '', None, 'a' * 31):
            with self.subTest(name=name), self.assertRaises(ValueError):
                project_path(self.root, name)
        self.project.rmdir()
        outside = self.root / 'outside'
        outside.mkdir()
        self.project.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            project_path(self.root, MANAGED_PROJECT_ID)
        self.assertNotEqual(self.launch('transfer_mcp.py').returncode, 0)

    def test_transfer_server_cannot_bind_an_outside_directory_with_an_allowed_name(self):
        outside = self.root / 'elsewhere' / MANAGED_PROJECT_ID
        outside.mkdir(parents=True)
        result = self.launch('transfer_mcp.py', outside)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('serverInfo', result.stdout)

    def test_uuid_projects_keep_working(self):
        project = self.project.parent / ('b' * 32)
        project.mkdir()
        self.assertEqual(project_path(self.root, project.name), project)
        self.assertEqual(self.launch('transfer_mcp.py', project).returncode, 0)


if __name__ == '__main__':
    unittest.main()
