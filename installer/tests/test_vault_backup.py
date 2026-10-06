import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'payload'))
import vault_backup as b
import vault_media as m


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / 'vault'
        (self.vault / 'Archive').mkdir(parents=True)
        (self.root / 'webui/data/uploads').mkdir(parents=True)
        (self.root / 'webui/data/uploads/note.txt').write_text('private')
        (self.root / 'control').mkdir()
        self.config = {'vault': {'enabled': True}, 'webui_secret': 'restore-key'}
        (self.root / 'control/config.json').write_text(json.dumps(self.config))
        self.patches = [patch.object(m, 'mounted_root', self.mounted), patch.object(b, 'mounted_root', self.mounted), patch('common.port_open', return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    @contextmanager
    def mounted(self, config):
        fd = os.open(self.vault, m.DIR_FLAGS)
        try:
            yield fd
        finally:
            os.close(fd)

    def test_snapshot_restores_sqlite_and_upload_and_preserves_old_data(self):
        db = self.root / 'webui/data/webui.db'
        connection = sqlite3.connect(db)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE chats (message TEXT)')
        connection.execute("INSERT INTO chats VALUES ('hello')")
        connection.commit()
        # Idle open connection retains WAL; backup must include it.
        archive = b.snapshot(self.root, self.config)
        connection.close()
        (self.root / 'webui/data/uploads/note.txt').write_text('newer')
        previous = b.restore(self.root, self.config, archive)
        self.assertEqual((previous / 'uploads/note.txt').read_text(), 'newer')
        self.assertEqual((self.root / 'webui/data/uploads/note.txt').read_text(), 'private')
        with sqlite3.connect(db) as restored:
            self.assertEqual(restored.execute('SELECT message FROM chats').fetchone()[0], 'hello')
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        with zipfile.ZipFile(self.vault / archive) as zipped:
            self.assertIn('webui-data/webui.db-wal', zipped.namelist())
            self.assertNotIn('github-token', str(zipped.namelist()))

    def test_active_services_block_snapshot_and_restore(self):
        with patch('common.port_open', return_value=True):
            with self.assertRaises(RuntimeError):
                b.snapshot(self.root, self.config)
            with self.assertRaises(RuntimeError):
                b.restore(self.root, self.config, 'anything')

    def test_symlink_aborts_without_archive_or_escape(self):
        (self.root / 'webui/data/uploads/link').symlink_to(self.root / 'control/config.json')
        with self.assertRaises(ValueError):
            b.snapshot(self.root, self.config)
        self.assertEqual(list((self.vault / 'Archive/Backups').iterdir()), [])

    def test_lock_during_copy_discards_partial(self):
        with patch.object(b, 'same_mount', side_effect=RuntimeError('locked')):
            with self.assertRaises(RuntimeError):
                b.snapshot(self.root, self.config)
        self.assertEqual(list((self.vault / 'Archive/Backups').iterdir()), [])

    def test_retention_three_and_legacy_sources_preserved(self):
        for _ in range(4):
            b.snapshot(self.root, self.config)
        self.assertEqual(len(list((self.vault / 'Archive/Backups').iterdir())), 3)
        (self.root / 'control/media').mkdir()
        original = self.root / 'control/media/old.png'
        original.write_bytes(b'old')
        archive = b.snapshot(self.root, self.config, legacy=True)
        with zipfile.ZipFile(self.vault / archive) as zipped:
            self.assertEqual(zipped.read('legacy/gateway-media/old.png'), b'old')
        self.assertEqual(original.read_bytes(), b'old')

    def test_media_migration_preserves_urls_and_never_overwrites(self):
        folder = self.root / 'control/media'
        folder.mkdir()
        (self.vault / 'Outputs').mkdir()
        name = 'a' * 32 + '.png'
        (folder / name).write_bytes(b'original')
        self.assertEqual(b.migrate_media(self.root, self.config), 1)
        (folder / name).write_bytes(b'changed')
        self.assertEqual(b.migrate_media(self.root, self.config), 0)
        self.assertEqual((self.vault / 'Outputs/Media' / name).read_bytes(), b'original')
        self.assertEqual((folder / name).read_bytes(), b'changed')

    def test_rebuildable_cache_symlinks_excluded(self):
        cache = self.root / 'webui/data/cache'
        cache.mkdir()
        (cache / 'model').symlink_to('/unavailable/model')
        archive = b.snapshot(self.root, self.config)
        with zipfile.ZipFile(self.vault / archive) as zipped:
            self.assertFalse(any('/cache/' in name for name in zipped.namelist()))

    def test_corrupt_restore_keeps_existing_data(self):
        archive = b.snapshot(self.root, self.config)
        with zipfile.ZipFile(self.vault / archive, 'a') as zipped:
            zipped.writestr('webui-data/uploads/note.txt', 'tampered')
        with self.assertRaises(ValueError):
            b.restore(self.root, self.config, archive)
        self.assertEqual((self.root / 'webui/data/uploads/note.txt').read_text(), 'private')
        self.assertFalse(list((self.root / 'webui').glob('.restore-*')))

if __name__ == '__main__':
    unittest.main()
