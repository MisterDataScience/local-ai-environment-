"""Dependency drift, hash enforcement and interrupted-install regressions."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import dependency_locks as locks
import installer
import voice_setup
import conversation_setup


class DependencyLockTests(unittest.TestCase):
    def test_all_requirements_are_exact_and_hashed(self):
        for path in (Path(locks.__file__).parent / 'locks').glob('*.txt'):
            text = path.read_text().replace('\\\n', '')
            requirements = [line.strip() for line in text.splitlines()
                            if line.strip() and not line.lstrip().startswith('#')]
            self.assertTrue(requirements, path)
            for line in requirements:
                with self.subTest(lock=path.name, requirement=line.split()[0]):
                    self.assertRegex(line, r'--hash=sha256:[0-9a-f]{64}')
                    self.assertRegex(line, r'^[a-zA-Z0-9_-]+(?:==[^\s]+| @ https://)')
                    if ' @ ' in line:
                        self.assertIn('200aac3c64e5140dbe0daa4570dcb129f0f7afc9.zip', line)
                        self.assertIn('sha256=92a1075616ecc5fefff6ac07280565b28d52162644e7a75ebd99d2a696ac64e9', line)

    def test_control_sync_always_checks_platform_and_dependency_consistency(self):
        run = Mock()
        for attempt in range(2):
            result = locks.install_locked('/uv', '/private/.venv/bin/python', 'control', run)
            self.assertEqual(result['lock_sha256'], hashlib.sha256(locks.lock_path('control').read_bytes()).hexdigest())
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn('Darwin', commands[0][-1])
        self.assertIn('(3, 11)', commands[0][-1])
        for command in (commands[1], commands[4]):
            self.assertIn('sync', command)
            self.assertIn('--require-hashes', command)
            self.assertIn('--only-binary', command)
            self.assertNotIn('--system', command)
        self.assertEqual(commands[2], ['/uv', 'pip', 'check', '--python', '/private/.venv/bin/python'])

    def test_voice_build_backend_is_locked_before_the_only_source_exception(self):
        run = Mock()
        result = locks.install_locked('/uv', '/voice/python', 'voice', run)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn('--no-deps', commands[1])
        self.assertIn('--require-hashes', commands[1])
        self.assertEqual(commands[1][-1], locks.lock_path('voice-build'))
        self.assertIn('--no-build-isolation', commands[2])
        self.assertEqual(commands[2][commands[2].index('--no-binary') + 1], 'mlx-audio')
        self.assertEqual(result['build_lock_sha256'], locks.receipt('voice-build')['lock_sha256'])

    def test_platform_failure_prevents_any_package_mutation(self):
        run = Mock(side_effect=subprocess.CalledProcessError(1, 'platform check'))
        with self.assertRaises(subprocess.CalledProcessError):
            locks.install_locked('/uv', '/python', 'voice', run)
        self.assertEqual(run.call_count, 1)

    def test_failed_speech_load_never_writes_success_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def run(command, **kwargs):
                if any('speech_worker.py' in str(p) for p in command):
                    raise RuntimeError('load failed')
            with self.assertRaisesRegex(RuntimeError, 'load failed'):
                voice_setup.install(root, '/uv', run)
            self.assertFalse((root / 'voice-engine/installed.json').exists())

    def test_old_voice_receipts_cannot_skip_new_lock_or_model_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine = root / 'voice-engine'
            (engine / 'model').mkdir(parents=True)
            (engine / 'stt').mkdir()
            (engine / 'model/config.json').write_text('{}')
            (engine / 'stt/config.json').write_text('{}')
            (engine / 'silero.onnx').write_bytes(b'model')
            for name in ('installed.json', 'conversation-installed.json'):
                (engine / name).write_text('{}')
            run = Mock()
            voice_setup.install(root, '/uv', run)
            conversation_setup.install(root, '/uv', run)
            self.assertEqual(sum('sync' in c.args[0] for c in run.call_args_list), 2)
            for name in ('installed.json', 'conversation-installed.json'):
                receipt = json.loads((engine / name).read_text())
                self.assertEqual(receipt['lock_sha256'], locks.receipt('voice')['lock_sha256'])
            self.assertTrue(any('speech_worker.py' in ' '.join(map(str,c.args[0])) for c in run.call_args_list))
            self.assertTrue(any('conversation_worker.py' in ' '.join(map(str,c.args[0])) for c in run.call_args_list))

    def environment(self, root, runner):
        (root / 'ComfyUI/custom_nodes').mkdir(parents=True, exist_ok=True)
        with patch.object(installer, 'run', runner), \
             patch('webui_local_images.harden'), patch('webui_local_images.harden_pdf'), \
             patch('voice_setup.install', return_value={'enabled': True}), \
             patch('conversation_setup.install', return_value={'enabled': True}):
            return installer.install_environments(root, '/uv', root / 'state.json')

    def test_installed_locks_and_repeat_install_ignore_stale_checkpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = Mock()
            for attempt in range(2):
                self.environment(root, run)
                for name in ('control', 'webui'):
                    receipt = json.loads((root / name / '.local-ai-dependencies.json').read_text())
                    self.assertEqual(receipt, locks.receipt(name))
            for name in locks.LOCKS:
                self.assertEqual((root / 'control/locks' / locks.lock_path(name).name).read_bytes(), locks.lock_path(name).read_bytes())
            self.assertEqual(sum('sync' in c.args[0] for c in run.call_args_list), 4)
            before = installer.acceptance_fingerprint(root)
            path = root / 'control/locks/control-macos-arm64-py311.txt'
            path.write_text(path.read_text() + '\n# changed\n')
            self.assertNotEqual(installer.acceptance_fingerprint(root), before)

    def test_failed_webui_sync_does_not_write_receipt_or_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def run(command, **kwargs):
                if 'sync' in command and any('webui-macos' in str(p) for p in command):
                    raise RuntimeError('hash mismatch')
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                self.environment(root, run)
            self.assertFalse((root / 'webui/.local-ai-dependencies.json').exists())
            self.assertFalse(installer.completed(root / 'state.json', 'webui-dependencies'))


if __name__ == '__main__':
    unittest.main()
