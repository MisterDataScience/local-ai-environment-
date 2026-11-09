"""Save the full rejected native result instead of requiring another file hunt."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
from team_setup import capture_handoff_failure


class HandoffDiagnosticTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / 'work-agent/acceptance/.local-ai-handoffs' / ('a' * 64 + '.json')
        self.source.parent.mkdir(parents=True)
        fixture = json.loads((ROOT / 'tests/fixtures/coder-matching-final-json.json').read_text())
        self.report = dict(fixture, status='needs_attention', issues=['Additional text alongside native structured final result.'])
        self.source.write_text(json.dumps(self.report))

    def test_saves_complete_native_result_and_reports_its_precise_rejection(self):
        original = self.source.read_bytes()
        output, detail = capture_handoff_failure(self.root, 'coder', 'parent', 'child', str(self.source))
        saved = json.loads(output.read_text())
        self.assertEqual(saved['stage'], 'specialist_result_validation')
        self.assertEqual(saved['report'], self.report)
        self.assertEqual(saved['child_session_id'], 'child')
        self.assertEqual(detail, self.report['issues'][0])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.source.read_bytes(), original)

    def test_outside_file_and_symlink_are_not_read(self):
        outside = self.root / 'private.json'
        outside.write_text('{"secret":"PRIVATE_OWNER_CONTENT"}')
        for path in (outside, self.source):
            if path == self.source:
                path.unlink()
                path.symlink_to(outside)
            output, detail = capture_handoff_failure(self.root, 'coder', 'parent', 'child', str(path))
            saved = json.loads(output.read_text())
            self.assertIn('outside', saved['report_read_error'])
            self.assertNotIn('PRIVATE_OWNER_CONTENT', output.read_text())
            self.assertNotIn('report', saved)
            self.assertEqual(detail, '')

    def test_unreadable_report_keeps_original_failure_identity(self):
        self.source.write_text('{partial JSON')
        output, detail = capture_handoff_failure(self.root, 'analyst', 'parent', 'child', str(self.source))
        saved = json.loads(output.read_text())
        self.assertEqual(saved['role'], 'analyst')
        self.assertIn('report_read_error', saved)
        self.assertEqual(self.source.read_text(), '{partial JSON')

    def test_oversized_report_is_bounded_without_truncating_it_into_false_evidence(self):
        self.source.write_bytes(b' ' * (2 * 1024 * 1024 + 1))
        output, detail = capture_handoff_failure(self.root, 'coder', 'parent', 'child', str(self.source))
        self.assertIn('exceeds 2 MiB', json.loads(output.read_text())['report_read_error'])


if __name__ == '__main__':
    unittest.main()
