"""Real ZIP extraction and filesystem repair, with network transfer mocked."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import installer


class SourceRepairTests(unittest.TestCase):
    def source(self, root):
        cache = root / 'cache'
        cache.mkdir()
        archive = cache / 'ComfyUI.zip'
        with zipfile.ZipFile(archive, 'w') as out:
            out.writestr('pinned/main.py', 'verified main')
            out.writestr('pinned/requirements.txt', 'verified requirements')
            out.writestr('pinned/comfy/module.py', 'verified module')
        return archive

    def test_partial_extraction_repairs_in_place_preserving_models(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.source(root)
            comfy = root / 'ComfyUI'
            (comfy / 'models').mkdir(parents=True)
            (comfy / 'models/model.gguf').write_bytes(b'owner model')
            (comfy / 'main.py').write_text('verified main')
            with patch.object(installer, 'download'):
                installer.ensure_comfy_source(root)
                installer.ensure_comfy_source(root)
            self.assertEqual((comfy / 'comfy/module.py').read_text(), 'verified module')
            self.assertEqual((comfy / 'models/model.gguf').read_bytes(), b'owner model')
            self.assertFalse((comfy / 'pinned').exists())

    def test_changed_source_is_never_blessed_or_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.source(root)
            comfy = root / 'ComfyUI'; comfy.mkdir()
            (comfy / 'main.py').write_text('owner edit')
            with patch.object(installer, 'download'), patch.object(installer, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'differs from pinned'):
                    installer.install_comfy(root, Path('/uv'), root / 'state.json')
            self.assertEqual((comfy / 'main.py').read_text(), 'owner edit')
            self.assertFalse((comfy / '.local-ai-dependencies.json').exists())
            run.assert_not_called()

    def test_source_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.source(root)
            comfy = root / 'ComfyUI'; comfy.mkdir()
            external = root / 'external'; external.mkdir()
            (comfy / 'comfy').symlink_to(external, target_is_directory=True)
            with patch.object(installer, 'download'):
                with self.assertRaisesRegex(RuntimeError, 'symlink'):
                    installer.ensure_comfy_source(root)
            self.assertFalse((external / 'module.py').exists())

    def test_rejected_resume_restarts_once_then_verifies_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'tool.dmg'
            target.with_name('tool.dmg.part').write_bytes(b'incomplete')
            content = b'complete verified bytes'
            def run(command, **kw):
                if '-C' in command:
                    raise subprocess.CalledProcessError(33, command)
                Path(command[command.index('-o') + 1]).write_bytes(content)
            with patch.object(installer, 'run', side_effect=run) as calls:
                installer.download('https://example.test/tool', target, hashlib.sha256(content).hexdigest())
            self.assertEqual(calls.call_count, 2)
            self.assertEqual(target.read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
