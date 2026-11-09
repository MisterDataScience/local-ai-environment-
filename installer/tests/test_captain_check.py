"""Capture the real saved failure when native Captain acceptance stops."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
import captain_check
from turnkey_install import ReadinessError


class CaptainFailureTests(unittest.TestCase):
    def test_failure_keeps_primary_reason_and_saves_diagnostic_without_more_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'control').mkdir()
            (root / 'control/config.json').write_text('{"api_key":"test-only-key"}')
            with patch.object(captain_check, '_verify', side_effect=ReadinessError('No native dispatch')) as probe:
                with self.assertRaisesRegex(ReadinessError, 'No native dispatch; diagnostic='):
                    captain_check.verify(root, {'captain': {'enabled': True}})
            probe.assert_called_once()
            report = json.loads((root / 'logs/native-acceptance/captain-diagnostic.json').read_text())
            self.assertEqual(report['check_failure'], 'No native dispatch')
            self.assertFalse(report['new_inference_requested'])

    def test_diagnostic_save_failure_cannot_hide_the_native_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(captain_check, '_verify', side_effect=ReadinessError('Original native failure')), \
                 patch('acceptance_diagnostics.collect', side_effect=OSError('Collection unavailable')):
                with self.assertRaisesRegex(ReadinessError, 'Original native failure; diagnostic capture failed: Collection unavailable'):
                    captain_check.verify(Path(folder), {})

    def test_disabled_captain_remains_an_unqualified_skip(self):
        with patch('acceptance_diagnostics.collect') as collect:
            self.assertEqual(captain_check.verify(Path('/unused'), {'captain': {'enabled': False}}), [])
        collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
