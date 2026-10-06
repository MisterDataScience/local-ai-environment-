import hashlib
import json
import os
from pathlib import Path
import sys
import stat
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vault_tools as v
from model_engine import Engine


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        for folder in v.FOLDERS:
            (self.root / folder).mkdir()
        self.config = {'vault': {'enabled': True, 'mount_path': str(self.root), 'id': 'test'}}
        (self.root / v.MARKER).write_text('test')

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def mounted(self, config):
        # File operation tests use real descriptors; only the mount boundary is simulated.
        fd = os.open(self.root, v.DIR_FLAGS)
        try:
            yield fd
        finally:
            os.close(fd)

    def call(self, name, **kwargs):
        with patch.object(v, 'mounted_root', self.mounted):
            return v.execute(self.config, name, kwargs)

    def test_create_read_and_revision_checked_edit(self):
        first = self.call('workspace_write', path='Outputs/note.md', content='first', expected_sha256='')
        self.assertEqual(self.call('workspace_read', path='Outputs/note.md')['content'], 'first')
        with self.assertRaises(FileExistsError):
            self.call('workspace_write', path='Outputs/note.md', content='overwrite', expected_sha256='')
        with self.assertRaises(ValueError):
            self.call('workspace_write', path='Outputs/note.md', content='stale', expected_sha256='a'*64)
        self.call('workspace_write', path='Outputs/note.md', content='second', expected_sha256=first['sha256'])
        self.assertEqual((self.root / 'Outputs/note.md').read_text(), 'second')

    def test_traversal_absolute_and_symlink_escape_denied(self):
        for p in ('../outside', '/etc/passwd', 'Outputs/../x', 'Outputs//x', 'Outputs/./x', 'Outputs\\x', 'Outputs/x\x00'):
            with self.assertRaises(ValueError):
                self.call('workspace_read', path=p)
        (self.root / 'Outputs/link').symlink_to(self.root / 'Projects', target_is_directory=True)
        with self.assertRaises(OSError):
            self.call('workspace_write', path='Outputs/link/x', content='escape', expected_sha256='')
        self.assertFalse((self.root / 'Projects/x').exists())
        (self.root / 'Outputs/file').symlink_to(self.root / v.MARKER)
        with self.assertRaises(OSError):
            self.call('workspace_read', path='Outputs/file')

    def test_special_and_hardlinked_files_denied(self):
        os.mkfifo(self.root / 'Outputs/fifo')
        with self.assertRaises(ValueError):
            self.call('workspace_read', path='Outputs/fifo')
        (self.root / 'Outputs/original').write_text('secret')
        os.link(self.root / 'Outputs/original', self.root / 'Outputs/link')
        with self.assertRaises(ValueError):
            self.call('workspace_read', path='Outputs/link')

    def test_missing_or_ordinary_mount_never_creates_fallback(self):
        with self.assertRaises(RuntimeError):
            v.execute(self.config, 'workspace_write', {'path': 'Outputs/x', 'content': 'secret', 'expected_sha256': ''})
        self.assertFalse((self.root / 'Outputs/x').exists())
        self.config['vault']['mount_path'] += '/missing'
        with self.assertRaises(RuntimeError):
            with v.mounted_root(self.config):
                pass
        self.assertFalse((self.root / 'missing').exists())

    def test_disabled_workspace_fails(self):
        with self.assertRaises(RuntimeError):
            with v.mounted_root({}):
                pass

    def test_real_mount_root_checks_marker_and_device(self):
        original = os.fstat
        def different_device(fd):
            result = original(fd)
            if stat.S_ISDIR(result.st_mode):
                return Mock(st_dev=result.st_dev+1000, st_ino=result.st_ino, st_mode=result.st_mode)
            return result
        # A marker alone on an ordinary filesystem never authorizes access.
        with patch.object(v.os.path, 'ismount', return_value=True):
            with self.assertRaises(RuntimeError):
                with v.mounted_root(self.config):
                    pass
        (self.root / v.MARKER).write_text('different-vault')
        with patch.object(v.os.path, 'ismount', return_value=True), patch.object(v.os, 'fstat', side_effect=different_device):
            with self.assertRaisesRegex(RuntimeError, 'not the configured'):
                with v.mounted_root(self.config):
                    pass

    def test_unmount_between_calls_blocks_next_operation(self):
        self.call('workspace_write', path='Inbox/ok', content='ok', expected_sha256='')
        with self.assertRaises(RuntimeError):
            v.execute(self.config, 'workspace_read', {'path': 'Inbox/ok'})

    def test_directory_and_limits(self):
        self.call('workspace_mkdir', path='Projects/test')
        self.assertEqual(self.call('workspace_list', path='Projects')['entries'][0]['name'], 'test')
        with self.assertRaises(ValueError):
            self.call('workspace_write', path='Outputs/x', content='x'*(v.LIMIT+1), expected_sha256='')
        with self.assertRaises(ValueError):
            self.call('workspace_read', path='Outputs/x', password='not-accepted')

    def test_media_is_blocked_before_loading_or_writing(self):
        engine = Engine(self.config, root=self.root)
        try:
            with patch.object(engine, 'unload_ollama') as unload:
                with self.assertRaisesRegex(RuntimeError, 'blocked in vault mode'):
                    engine.render('image', 'private prompt')
                unload.assert_not_called()
        finally:
            engine.executor.shutdown()

    def test_spec_exposes_only_bounded_operations(self):
        spec = v.specification()
        self.assertEqual(len(spec['paths']), 4)
        self.assertNotIn('password', json.dumps(spec))
        self.assertEqual(spec['security'], [{'bearerAuth': []}])

class VaultHTTPTests(unittest.TestCase):
    def test_authentication_locked_failure_and_media_isolation(self):
        from http.server import ThreadingHTTPServer
        import threading
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from http_api import Handler, MediaHandler
        for handler in (Handler, MediaHandler):
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            server.engine = Mock(config={'api_key': 'test', 'vault': {'enabled': True}})
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/workspace/openapi.json', timeout=2)
                self.assertEqual(error.exception.code, 401 if handler is Handler else 404)
                request = Request(base + '/workspace/workspace_read', data=b'{"path":"Inbox/a"}',
                                  headers={'Authorization': 'Bearer test'})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request, timeout=2)
                self.assertEqual(error.exception.code, 409 if handler is Handler else 404)
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/media/legacy.png', timeout=2)
                self.assertEqual(error.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)


if __name__ == '__main__':
    unittest.main()
