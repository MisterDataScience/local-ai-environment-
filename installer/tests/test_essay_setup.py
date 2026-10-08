import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import essay_setup


class EssaySetupTests(unittest.TestCase):
    def test_selected_utf8_draft_preserves_line_endings_and_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'essay.txt'; raw = b'First.\r\n\r\nSecond.\n'; path.write_bytes(raw)
            request = essay_setup.read_draft(path)
            self.assertEqual(request['draft'].encode(), raw)
            self.assertEqual(request['reorder'], 'none'); self.assertFalse(request['randomiser'])
            unsupported = Path(folder)/'essay.docx'; unsupported.write_bytes(raw)
            with self.assertRaises(ValueError):essay_setup.read_draft(unsupported)

    def test_draft_is_api_data_never_a_native_command(self):
        calls = []
        def reply(req, **kwargs):
            calls.append((req.full_url,json.loads(req.data)))
            response = Mock(); response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=False)
            response.read.return_value=b'{"id":"session1"}' if req.full_url.endswith('/session') else b''
            return response
        with patch.object(essay_setup,'urlopen',side_effect=reply):
            essay_setup.submit('private',{'draft':'Literal !`do-not-execute` and @file.'})
        self.assertTrue(calls[1][0].endswith('/prompt_async'))
        text = calls[1][1]['parts'][0]['text']
        self.assertEqual(json.loads(text.split('\n',1)[1])['draft'],'Literal !`do-not-execute` and @file.')

    def test_existing_harness_attachment_uses_private_record_and_cleanup(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'work-agent/state').mkdir(parents=True)
            essay_setup.publish_connection(root,'secret')
            path=essay_setup.connection_file(root)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with patch.object(essay_setup,'submit',return_value='new-session') as submit:
                self.assertEqual(essay_setup.attach(root,{'draft':'Essay'}),'new-session')
                submit.assert_called_once_with('secret',{'draft':'Essay'})
                path.chmod(0o644)
                with self.assertRaises(RuntimeError):essay_setup.attach(root,{'draft':'Essay'})
            essay_setup.clear_connection(root,'other-secret');self.assertTrue(path.exists())
            essay_setup.clear_connection(root,'secret');self.assertFalse(path.exists())
