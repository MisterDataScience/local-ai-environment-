import errno
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

INSTALLER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INSTALLER))
sys.path.insert(0, str(INSTALLER / 'payload'))

from vault_transfer import copy_new


class VaultTransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.txt'
        self.source.write_text('Workspace check 7294')
        self.destination = self.root / 'destination'
        self.destination.mkdir()
        self.source_fd = os.open(self.source, os.O_RDONLY)
        self.destination_fd = os.open(self.destination, os.O_RDONLY | os.O_DIRECTORY)

    def tearDown(self):
        os.close(self.source_fd)
        os.close(self.destination_fd)
        self.temporary.cleanup()

    def copy(self, check_mount=None):
        copy_new(self.source_fd, self.destination_fd, 'workspace-check.txt', check_mount)

    def test_hardlink_unsupported_falls_back_to_exclusive_copy(self):
        unsupported = OSError(errno.EOPNOTSUPP, 'Operation not supported')
        with mock.patch('vault_transfer.os.link', side_effect=unsupported), \
             mock.patch('vault_transfer._rename_exclusive', return_value=False):
            self.copy()
        target = self.destination / 'workspace-check.txt'
        self.assertEqual(target.read_text(), 'Workspace check 7294')
        self.assertEqual([path.name for path in self.destination.iterdir()], [target.name])

    def test_hardlink_unsupported_uses_exclusive_rename_when_available(self):
        unsupported = OSError(errno.ENOTSUP, 'Operation not supported')
        def move(temp, name, directory_fd):
            os.rename(temp, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            return True
        with mock.patch('vault_transfer.os.link', side_effect=unsupported), \
             mock.patch('vault_transfer._rename_exclusive', side_effect=move):
            self.copy()
        target = self.destination / 'workspace-check.txt'
        self.assertEqual(target.read_text(), 'Workspace check 7294')
        self.assertEqual([path.name for path in self.destination.iterdir()], [target.name])

    def test_existing_destination_is_never_replaced(self):
        target = self.destination / 'workspace-check.txt'
        target.write_text('keep existing content')
        with mock.patch('vault_transfer._rename_exclusive', side_effect=AssertionError):
            with self.assertRaises(FileExistsError):
                self.copy()
        self.assertEqual(target.read_text(), 'keep existing content')
        self.assertEqual([path.name for path in self.destination.iterdir()], [target.name])

    def test_fallback_removes_partial_destination_on_failure(self):
        unsupported = OSError(errno.ENOTSUP, 'Operation not supported')
        calls = 0
        def check_mount():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError('vault mount changed during fallback copy')
        with mock.patch('vault_transfer.os.link', side_effect=unsupported), \
             mock.patch('vault_transfer._rename_exclusive', return_value=False):
            with self.assertRaisesRegex(OSError, 'vault mount changed'):
                self.copy(check_mount)
        self.assertEqual(list(self.destination.iterdir()), [])


if __name__ == '__main__':
    unittest.main()

