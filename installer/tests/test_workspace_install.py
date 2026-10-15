"""Captain installation must register only an explicitly confirmed mounted vault.

All desktop/iCloud behavior is mocked here. These tests do NOT demonstrate that
Cryptomator has actually mounted a volume on an Apple Silicon Mac.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE / 'payload')]
import workspace_install as setup
import vault_tools
from turnkey_install import write_receipt


class VaultInstallTests(unittest.TestCase):
    def test_mount_requires_explicit_owner_confirmation(self):
        target = Path('/Volumes/AI Workspace')
        prompts = []
        def ask(value):
            prompts.append(value)
            return 'NO'
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            setup.choose_mount(set(), {target}, ask, lambda msg: None)
        self.assertEqual(len(prompts), 1)
        self.assertIn('Type YES', prompts[0])

    def test_unrelated_mount_is_never_auto_selected(self):
        unexpected = Path('/Volumes/USB Backup')
        with self.assertRaisesRegex(RuntimeError, 'No decrypted Cryptomator volume'):
            setup.choose_mount(set(), {unexpected}, lambda _: '', lambda _: None)
        with self.assertRaisesRegex(RuntimeError, 'not a verified macOS mounted volume'):
            setup.choose_mount(set(), {unexpected}, lambda _: '/tmp/not-a-volume', lambda _: None)

    def test_fresh_named_volume_requires_confirmed_selection(self):
        target = Path('/Volumes/AI Workspace')
        self.assertEqual(setup.choose_mount(set(), {target}, lambda _: 'YES', lambda _: None), target)
        self.assertEqual(setup.choose_mount({target}, {target}, lambda _: 'YES', lambda _: None), target)

    def test_workspace_smoke_test_writes_reads_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Outputs').mkdir()
            @contextmanager
            def volume(_config):
                fd = os.open(root, vault_tools.DIR_FLAGS)
                try:
                    yield fd
                finally:
                    os.close(fd)
            config = {'vault': {'enabled': True, 'mount_path': str(root), 'id': 'fake-test-id'}}
            with patch.object(setup, 'mounted_root', volume), patch.object(vault_tools, 'mounted_root', volume):
                result = setup.verify_workspace(config)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['automatic_unlock'], False)
            self.assertEqual(list((root / 'Outputs').iterdir()), [])

    def test_missing_vault_is_never_registered_as_a_plaintext_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(RuntimeError):
                setup.verify_workspace({'vault': {'enabled': False}})
            self.assertEqual(list(root.iterdir()), [])

    def test_existing_vault_is_not_recreated_if_already_accessible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'control').mkdir()
            config = {'vault': {'enabled': True, 'id': 'original'}}
            (root / 'control/config.json').write_text(json.dumps(config))
            with patch.object(setup, 'verify_workspace', return_value={'status': 'passed'}) as verify, \
                 patch.object(setup.subprocess, 'run') as open_app, \
                 patch.object(setup, 'choose_mount') as choose:
                actual, report = setup.configure_during_install(
                    root, '/Applications/Cryptomator.app', prompt=lambda _: '', say=lambda _: None)
            self.assertEqual(actual, config)
            self.assertEqual(report['registration'], 'existing_verified')
            verify.assert_called_once()
            open_app.assert_not_called()
            choose.assert_not_called()

    def test_existing_locked_vault_retries_same_identity_without_replacing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'control').mkdir()
            config = {'vault': {'enabled': True, 'id': 'existing'}}
            path = root / 'control/config.json'
            path.write_text(json.dumps(config))
            with patch.object(setup, 'verify_workspace', side_effect=[
                RuntimeError('locked'), {'status': 'passed'}]) as verify, \
                 patch.object(setup.subprocess, 'run') as launch, \
                 patch.object(setup, 'choose_mount') as choose:
                actual, result = setup.configure_during_install(
                    root, '/Applications/Cryptomator.app', prompt=lambda _: '', say=lambda _: None)
            self.assertEqual(actual, config)
            self.assertEqual(result['registration'], 'existing_unlocked')
            self.assertEqual(verify.call_count, 2)
            launch.assert_called_once()
            choose.assert_not_called()
            self.assertEqual(json.loads(path.read_text()), config)

    def test_new_vault_registration_runs_during_install_not_later(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'control').mkdir()
            (root / 'control/config.json').write_text('{}')
            selected = Path('/Volumes/AI Workspace')
            prompt = Mock(side_effect=['', 'YES'])
            config = {'vault': {'enabled': True, 'id': 'verified'}}
            with patch.object(setup, 'mounted_volumes', side_effect=[[], [selected]]), \
                 patch.object(setup, 'verify_workspace', return_value={'status': 'passed'}), \
                 patch.object(setup.subprocess, 'run') as launch, \
                 patch('workspace_setup.register', return_value=config) as registered:
                actual, result = setup.configure_during_install(root, '/Applications/Cryptomator.app',
                                                                 prompt=prompt, say=lambda _: None)
            self.assertEqual(actual, config)
            self.assertEqual(result['registration'], 'created_or_selected_during_install')
            registered.assert_called_once_with(root, selected)
            launch.assert_called_once()
            self.assertEqual(prompt.call_count, 2)

    def test_receipt_rejects_unverified_encrypted_vault(self):
        config = {'captain': {'enabled': True, 'provider': 'llama'},
                  'vault': {'enabled': True}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'encrypted workspace tests'):
                write_receipt(root, config, {}, {}, vault=None)
            with self.assertRaisesRegex(RuntimeError, 'encrypted workspace tests'):
                write_receipt(root, config, {}, {}, vault={'status': 'not_run'})
            receipt = write_receipt(root, config, {}, {}, vault={'status': 'passed'})
            self.assertEqual(receipt['encrypted_workspace']['status'], 'passed')
            self.assertEqual(receipt['encrypted_workspace_login_unlock'],
                             'owner_must_unlock_cryptomator_after_login')
            self.assertNotIn('encrypted_vault', receipt['deferred_permissions_and_accounts'])


if __name__ == '__main__':
    unittest.main()
