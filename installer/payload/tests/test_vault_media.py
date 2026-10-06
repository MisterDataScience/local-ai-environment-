import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch, Mock
from http.server import ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vault_media as m
from model_engine import Engine
from http_api import MediaHandler
from PIL import Image


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        for folder in ('Outputs', 'Archive'):
            (self.root / folder).mkdir()
        self.config = {'vault': {'enabled': True}, 'public_url': 'https://test'}
        self.mount = patch.object(m, 'mounted_root', self.mounted)
        self.mount.start()

    def tearDown(self):
        self.mount.stop()
        self.temp.cleanup()

    @contextmanager
    def mounted(self, config):
        fd = os.open(self.root, m.DIR_FLAGS)
        try:
            yield fd
        finally:
            os.close(fd)

    def test_png_round_trip_without_staging(self):
        name = m.save_image(self.config, Image.new('RGB', (16, 16), 'red'))
        with m.open_media(self.config, name) as (src, size, fd):
            self.assertGreater(size, 0)
            self.assertEqual(Image.open(src).getpixel((0, 0)), (255, 0, 0))
        self.assertEqual([p.name for p in (self.root / 'Outputs/Media').iterdir()], [name])
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'Outputs', 'Archive'})

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required for real encode test')
    def test_real_mp4_pipe_encoding(self):
        name = m.encode_video(self.config, [bytes([200, 0, 0]) * 256] * 3, 16, 16, shutil.which('ffmpeg'))
        path = self.root / 'Outputs/Media' / name
        self.assertIn(b'ftyp', path.read_bytes()[:32])
        self.assertGreater(path.stat().st_size, 100)
        self.assertEqual(len(list(path.parent.iterdir())), 1)

    def test_mount_loss_discards_partial(self):
        with patch.object(m, 'same_mount', side_effect=RuntimeError('locked')):
            with self.assertRaises(RuntimeError):
                m.save_image(self.config, Image.new('RGB', (8, 8)))
        self.assertEqual(list((self.root / 'Outputs/Media').iterdir()), [])

    def test_output_symlink_rejected(self):
        (self.root / 'Outputs/Media').symlink_to(self.root / 'Archive', target_is_directory=True)
        with self.assertRaises(OSError):
            m.save_image(self.config, Image.new('RGB', (8, 8)))
        self.assertEqual(list((self.root / 'Archive').iterdir()), [])

    def test_bundled_workflows_replace_disk_savers_and_reject_extra_nodes(self):
        for kind, expected in [('image', 'LocalAIVaultImage'), ('video', 'LocalAIVaultVideo')]:
            original = json.loads((Path(__file__).resolve().parents[1] / 'workflows' / (kind + '.json')).read_text())
            result = m.encrypted_workflow(original, kind)
            classes = [node['class_type'] for node in result.values()]
            self.assertIn(expected, classes)
            self.assertNotIn('SaveImage', classes)
            self.assertNotIn('SaveAnimatedWEBP', classes)
            self.assertNotEqual(original, result)
            original['bad'] = {'class_type': 'PreviewImage', 'inputs': {}}
            with self.assertRaises(ValueError):
                m.encrypted_workflow(original, kind)

    def test_http_ranges_and_lock_no_fallback(self):
        name = m.save_image(self.config, Image.new('RGB', (16, 16)))
        server = ThreadingHTTPServer(('127.0.0.1', 0), MediaHandler)
        server.engine = Mock(config=self.config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/media/{name}'
            with urlopen(Request(url, headers={'Range': 'bytes=0-7'}), timeout=2) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertEqual(response.read(), b'\x89PNG\r\n\x1a\n')
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url, headers={'Range': 'bytes=999999-'}), timeout=2)
            self.assertEqual(error.exception.code, 416)
            with patch.object(m, 'mounted_root', side_effect=RuntimeError('locked')):
                with self.assertRaises(HTTPError) as error:
                    urlopen(url, timeout=2)
                self.assertEqual(error.exception.code, 409)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_engine_returns_vault_output_and_always_releases_comfy(self):
        workflow_dir = self.root / 'workflows'
        shutil.copytree(Path(__file__).resolve().parents[1] / 'workflows', workflow_dir)
        name = m.save_image(self.config, Image.new('RGB', (16, 16)))
        engine = Engine(self.config, root=self.root)
        engine.process = Mock()
        engine.process.poll.return_value = None
        def api(url, route, *args, **kwargs):
            if route == '/prompt':
                self.assertIn('LocalAIVaultImage', str(args[0]))
                return {'prompt_id': 'test'}
            return {'test': {'status': {'completed': True}, 'outputs': {'1': {'images': [
                {'filename': name, 'subfolder': 'Media', 'type': 'output'}]}}}}
        try:
            with patch('model_engine.mounted_root', self.mounted), patch('model_engine.api', side_effect=api), patch.object(engine, 'start_comfy'), patch.object(engine, 'stop_comfy') as stop, patch.object(engine, 'unload_ollama') as unload:
                self.assertIn(name, engine.render('image', 'sample'))
                unload.assert_called_once()
                stop.assert_called_once()
                self.assertEqual(list((self.root / 'media').iterdir()), [])
        finally:
            engine.executor.shutdown()

if __name__ == '__main__':
    unittest.main()
