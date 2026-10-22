"""Studio intake and evidence persistence without a compiler or model runtime."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]),
               str(Path(__file__).resolve().parents[1] / 'payload')]
import village
from studio_store import Store, sha
from studio_workbench import Workbench


class StudioPersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'village'
        self.connector = lambda path: village.connect(path, test_encrypted=True)
        self.store = Store(self.root, self.connector)
        self.institution = self.store.create('Persistence fixture', 'Regression tests')['id']
        self.project = self.store.ingest(
            self.institution, 'Source fixture', [('game.c', b'int counter;\n')],
            dict(kind='fixture'))
        self.pid = self.project['project']

    def approve(self, proposal):
        preview = self.store.preview(proposal['id'])
        return self.store.review(proposal['id'], preview['review_digest'], 'approve')

    def test_intake_and_approved_document_manifest_survive_reopen(self):
        manifest = self.store.get_project_manifest(self.institution, self.pid)
        self.assertEqual(manifest['source']['sha256'], self.project['sha256'])
        self.assertEqual(manifest['working_copy']['files'][0]['sha256'], sha(b'int counter;\n'))
        evidence = [dict(source=self.project['source'], path='game.c',
                         digest=sha(b'int counter;\n'), quote='int counter;')]
        document = self.approve(self.store.propose(
            self.institution, 'library', dict(title='Counter', text='The source declares a counter.'),
            evidence))['citation']
        reopened = Store(self.root, self.connector)
        manifest = reopened.get_project_manifest(self.institution, self.pid)
        self.assertIn(document, [item['id'] for item in manifest['approved_documents']])
        self.assertTrue(reopened.recovery_check(self.institution, self.pid)['ok'])

    def seed_evidence(self):
        # An authored evidence record isolates persistence from Wasm execution.
        workbench = Workbench(self.store)
        build = 'build:' + 'a' * 32
        evidence = 'evidence:' + 'b' * 32
        meta = dict(institution=self.institution, project=self.pid, build=build)
        record = dict(id=evidence, project=self.pid, build=build, findings=[], updated=0)
        workbench.write_evidence(meta, record)
        return workbench, evidence, workbench.evidence_path(meta, evidence)

    def test_finding_updates_evidence_and_recovery_manifest(self):
        workbench, evidence, path = self.seed_evidence()
        before = sha(path.read_bytes())
        result = workbench.add_finding(
            self.institution, self.pid, 'Observed', 'The fixture declares a counter.', [evidence])
        self.assertTrue(result['saved'])
        record = json.loads(path.read_text())
        self.assertEqual(record['findings'][-1]['text'], 'The fixture declares a counter.')
        self.assertEqual(record['findings'][-1]['category'], 'Observed')
        self.assertNotEqual(sha(path.read_bytes()), before)
        reopened = Store(self.root, self.connector)
        manifest = reopened.get_project_manifest(self.institution, self.pid)
        entry = next(item for item in manifest['evidence'] if item['id'] == evidence)
        self.assertEqual(entry['sha256'], sha(path.read_bytes()))
        self.assertTrue(reopened.recovery_check(self.institution, self.pid)['ok'])

    def test_finding_cannot_modify_another_projects_evidence(self):
        workbench, evidence, path = self.seed_evidence()
        other = self.store.ingest(self.institution, 'Other source',
                                  [('other.c', b'int unrelated;\n')], dict(kind='fixture'))
        before = path.read_bytes()
        with self.assertRaises(PermissionError):
            workbench.add_finding(self.institution, other['project'], 'Observed',
                                  'Wrong project', [evidence])
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
