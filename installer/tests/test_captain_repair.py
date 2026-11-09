"""Real-file, transactional application of the scoped Captain repair."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
import feature_install
from feature_state import installation_lock
import repair_captain as repair


class CaptainRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.root, self.source = base / 'installed', base / 'source'
        (self.root / 'control').mkdir(parents=True)
        self.source.mkdir()
        self.originals = {'captain.mjs': b'// old native policy\n', 'captain_check.py': b'# old acceptance\n'}
        self.new = {'captain.mjs': b'// repaired native policy\n',
                    'captain_check.py': b'# diagnostic acceptance\n',
                    'acceptance_diagnostics.py': b'# saved native diagnostics\n'}
        self.baseline = {name: hashlib.sha256(content).hexdigest() for name, content in self.originals.items()}
        self.baseline['acceptance_diagnostics.py'] = None
        for name, content in self.originals.items():
            (self.root / 'control' / name).write_bytes(content)
        for name, content in self.new.items():
            (self.source / name).write_bytes(content)
        self.manifest()
        self.config = self.root / 'control/config.json'
        self.config.write_text('{"api_key":"owner-key","thinking":true}')
        self.receipt = self.root / 'accepted-core-fingerprint.txt'
        self.receipt.write_text('existing acceptance receipt')
        self.addCleanup(patch.stopall)
        patch.object(repair, 'BASELINE', self.baseline).start()
        self.stopped = patch.object(feature_install, 'ensure_stopped').start()
        previous = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous))

    def manifest(self):
        (self.source / 'RELEASE.json').write_text(json.dumps({'files': {
            name: hashlib.sha256((self.source / name).read_bytes()).hexdigest() for name in self.new}}))

    def unchanged(self):
        for name, content in self.originals.items():
            self.assertEqual((self.root / 'control' / name).read_bytes(), content)
        self.assertFalse((self.root / 'control/acceptance_diagnostics.py').exists())

    def test_applies_exactly_three_files_and_repeats_without_replacing_backups(self):
        first = repair.apply(self.root, self.source)
        self.assertEqual(first['status'], 'applied')
        self.assertEqual(set(first['files']), set(self.new))
        self.assertEqual(len(first['backups']), 2)
        for name, content in self.new.items():
            self.assertEqual((self.root / 'control' / name).read_bytes(), content)
        for name, content in self.originals.items():
            self.assertEqual((self.root / 'control' / (name + '.before-captain-dispatch-fix')).read_bytes(), content)
        self.assertEqual(repair.apply(self.root, self.source)['status'], 'already_applied')
        self.assertEqual(json.loads(self.config.read_text())['api_key'], 'owner-key')
        self.assertTrue(json.loads(self.config.read_text())['thinking'])
        self.assertEqual(self.receipt.read_text(), 'existing acceptance receipt')
        self.assertEqual(self.stopped.call_count, 2)

    def test_unknown_installed_version_stops_before_any_replacement(self):
        path = self.root / 'control/captain_check.py'
        path.write_bytes(b'# owner changes\n')
        with self.assertRaisesRegex(RuntimeError, 'diagnosed version: captain_check.py'):
            repair.apply(self.root, self.source)
        self.assertEqual((self.root / 'control/captain.mjs').read_bytes(), self.originals['captain.mjs'])
        self.assertEqual(path.read_bytes(), b'# owner changes\n')
        self.assertFalse((self.root / 'control/acceptance_diagnostics.py').exists())

    def test_known_previous_diagnostic_can_be_upgraded_without_replacing_policy(self):
        previous = b'# previous diagnostic version\n'
        self.baseline['acceptance_diagnostics.py'] = (None, hashlib.sha256(previous).hexdigest())
        for name, content in self.new.items():
            (self.root / 'control' / name).write_bytes(content)
        (self.root / 'control/acceptance_diagnostics.py').write_bytes(previous)
        result = repair.apply(self.root, self.source)
        self.assertEqual(result['files'], ['acceptance_diagnostics.py'])
        backup = self.root / 'control/acceptance_diagnostics.py.before-captain-dispatch-fix'
        self.assertEqual(backup.read_bytes(), previous)
        self.assertEqual(repair.apply(self.root, self.source)['status'], 'already_applied')

    def test_invalid_source_manifest_preserves_installed_files(self):
        (self.source / 'acceptance_diagnostics.py').write_bytes(b'# changed after packaging\n')
        with self.assertRaisesRegex(RuntimeError, 'release manifest'):
            repair.apply(self.root, self.source)
        self.unchanged()

    def test_invalid_python_source_stops_before_any_replacement(self):
        (self.source / 'acceptance_diagnostics.py').write_bytes(b'broken python syntax:')
        self.manifest()
        with self.assertRaises(SyntaxError):
            repair.apply(self.root, self.source)
        self.unchanged()

    def test_symlink_target_cannot_change_an_external_file(self):
        external = self.root / 'owner.py'
        external.write_bytes(self.originals['captain_check.py'])
        target = self.root / 'control/captain_check.py'
        target.unlink()
        target.symlink_to(external)
        with self.assertRaisesRegex(RuntimeError, 'Symbolic links'):
            repair.apply(self.root, self.source)
        self.assertEqual(external.read_bytes(), self.originals['captain_check.py'])
        self.assertEqual((self.root / 'control/captain.mjs').read_bytes(), self.originals['captain.mjs'])

    def test_running_installation_prevents_repair(self):
        with installation_lock(self.root):
            with self.assertRaisesRegex(RuntimeError, 'Another installer'):
                repair.apply(self.root, self.source)
        self.unchanged()
        self.stopped.assert_not_called()

    def test_partial_write_failure_rolls_back_files_and_preserves_original_backups(self):
        write = repair.atomic_bytes
        attempts = 0
        def fail_once(path, content):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError('Simulated disk failure')
            write(path, content)
        with patch.object(repair, 'atomic_bytes', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'Simulated disk failure'):
                repair.apply(self.root, self.source)
        self.unchanged()
        self.assertEqual((self.root / 'control/captain.mjs.before-captain-dispatch-fix').read_bytes(), self.originals['captain.mjs'])

    def test_existing_different_backup_is_never_overwritten(self):
        backup = self.root / 'control/captain_check.py.before-captain-dispatch-fix'
        backup.write_bytes(b'older owner backup')
        with self.assertRaisesRegex(RuntimeError, 'Existing repair backup differs'):
            repair.apply(self.root, self.source)
        self.unchanged()
        self.assertEqual(backup.read_bytes(), b'older owner backup')


if __name__ == '__main__':
    unittest.main()
