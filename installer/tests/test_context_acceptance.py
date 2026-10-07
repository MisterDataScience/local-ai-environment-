import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import installer

class ContextAcceptanceTests(unittest.TestCase):
    def test_upgrade_verifies_candidate_before_preserving_old_app(self):
        for fail_candidate in (False, True):
            with self.subTest(fail_candidate=fail_candidate), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'cache').mkdir()
                old = root / 'tools/Ollama.app/Contents/Resources/ollama'
                old.parent.mkdir(parents=True)
                old.write_text('old')
                def download(url, destination, checksum):
                    self.assertIn('/v0.40.0/', url)
                    self.assertEqual(checksum, installer.OLLAMA_CONTEXT_SHA256)
                    with zipfile.ZipFile(destination, 'w') as archive:
                        archive.writestr('Ollama.app/Contents/Resources/ollama', 'new')
                def run(command):
                    if command[0] == '/usr/bin/ditto':
                        with zipfile.ZipFile(command[2]) as archive:
                            archive.extractall(command[3])
                versions = [RuntimeError('old'), RuntimeError('bad candidate') if fail_candidate else '0.40.0']
                with patch.object(installer, 'download', side_effect=download), patch.object(installer, 'run', side_effect=run), patch.object(installer, 'ollama_client_version', side_effect=versions):
                    if fail_candidate:
                        with self.assertRaisesRegex(RuntimeError, 'bad candidate'):
                            installer.install_ollama(root)
                    else:
                        installer.install_ollama(root)
                self.assertEqual(old.read_text(), 'old' if fail_candidate else 'new')
                backups = list((root / 'tools').glob('Ollama.app.before-context-*'))
                self.assertEqual(len(backups), 0 if fail_candidate else 1)
                if backups:
                    self.assertEqual((backups[0] / 'Contents/Resources/ollama').read_text(), 'old')

    def test_all_native_overflow_cases_must_return_specific_error(self):
        calls = []
        def reject(url, body, **kwargs):
            calls.append(body)
            raise HTTPError(url, 400, 'overflow', {}, io.BytesIO(b'{"error":{"code":"context_length_exceeded"}}'))
        with patch.object(installer, 'http', side_effect=reject):
            result = installer.verify_context_rejection('test', 'local-ai-small', 4096)
        self.assertEqual([x['case'] for x in result], ['first-message', 'old-history', 'tool-result', 'tool-schema'])
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(x['max_completion_tokens'] == 1 for x in calls))
        self.assertEqual(calls[1]['messages'][0]['role'], 'system')
        self.assertEqual(calls[2]['messages'][2]['role'], 'tool')
        self.assertGreater(len(calls[3]['tools'][0]['function']['description']), 4096 * 4)
        for status, code in [(502, 'backend_error'), (400, 'invalid_request_error')]:
            error = HTTPError('test', status, 'error', {}, io.BytesIO(('{"error":{"code":"' + code + '"}}').encode()))
            with patch.object(installer, 'http', side_effect=error), self.assertRaisesRegex(RuntimeError, 'unexpected error'):
                installer.verify_context_rejection('test', 'local-ai-small', 4096)
        with patch.object(installer, 'http', return_value={}), self.assertRaisesRegex(RuntimeError, 'oversized input was accepted'):
            installer.verify_context_rejection('test', 'local-ai-small', 4096)

    def test_private_cli_version_prefers_client_and_rejects_old_or_unknown(self):
        for output, expected in [('ollama version is 0.40.0', '0.40.0'),
                                 ('ollama version is 0.99.0\nWarning: client version is 0.40.0', '0.40.0')]:
            with patch.object(installer.subprocess, 'check_output', return_value=output):
                self.assertEqual(installer.ollama_client_version(Path('/private/ollama'), Path('/private')), expected)
        for output in ['unknown', 'ollama version is 0.39.0', 'ollama version is 0.99.0\nclient version is 0.39.0']:
            with patch.object(installer.subprocess, 'check_output', return_value=output), self.assertRaises(RuntimeError):
                installer.ollama_client_version(Path('/private/ollama'), Path('/private'))

    def test_supported_private_backend_does_not_download_or_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'tools/Ollama.app/Contents/Resources/ollama'
            binary.parent.mkdir(parents=True)
            binary.write_text('existing private app')
            with patch.object(installer, 'ollama_client_version', return_value='0.40.0'), patch.object(installer, 'download') as download:
                installer.install_ollama(root)
            download.assert_not_called()
            self.assertEqual(binary.read_text(), 'existing private app')
