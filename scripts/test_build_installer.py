"""A stale package must fail instead of shipping silently."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from build_installer import build, verify


class PackageTests(unittest.TestCase):
    def test_reproducible_and_detects_stale_source_missing_files_and_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'installer/payload').mkdir(parents=True)
            (root / 'docs').mkdir()
            source = root / 'installer/payload/gateway.py'
            source.write_text('fixture\n')
            (root / 'installer/Install Local AI.command').write_text('#!/bin/bash\n')
            (root / 'docs/DEPLOYMENT.md').write_text('fixture guide\n')
            archive = root / 'installer.zip'
            other = root / 'other.zip'
            build(root, archive)
            build(root, other)
            self.assertEqual(archive.read_bytes(), other.read_bytes())
            source.write_text('changed\n')
            with self.assertRaisesRegex(ValueError, 'differs from source'):
                verify(root, archive)
            build(root, archive)
            with zipfile.ZipFile(archive) as original, zipfile.ZipFile(other, 'w') as bad:
                for entry in original.infolist():
                    if not entry.filename.endswith('gateway.py'):
                        bad.writestr(entry, original.read(entry))
            with self.assertRaisesRegex(ValueError, 'manifest differs'):
                verify(root, other)
            with zipfile.ZipFile(archive) as original, zipfile.ZipFile(other, 'w') as bad:
                for entry in original.infolist():
                    if entry.filename.endswith('.command'):
                        entry.external_attr = 0o100644 << 16
                    bad.writestr(entry, original.read(entry))
            with self.assertRaisesRegex(ValueError, 'permissions differ'):
                verify(root, other)


if __name__ == '__main__':
    unittest.main()
