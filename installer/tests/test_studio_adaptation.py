"""Read-only boundary for the legacy adaptation planning session."""
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studios import Studios


class StoreStub:
    @contextmanager
    def db(self):
        yield object()

    def member(self, cx, institution, actor):
        return 'Lead Designer'

    def project(self, cx, project, institution):
        return dict(id=project)


class AdaptationPlanPolicyTests(unittest.TestCase):
    def setUp(self):
        self.studios = Studios.__new__(Studios)
        self.studios.store = StoreStub()
        self.row = dict(
            id='studio-job:test',
            institution='institution:test',
            project='project:test',
            kind='adaptation-plan',
            settings=json.dumps({
                'actor': 'studio.lead',
                'adaptation': {'source': 'studio-source:source', 'material': 'inspect', 'experiment': 'movement'},
            }),
        )

    def test_plan_cannot_mutate_or_run_workbench(self):
        progress = {'notes': ''}
        blocked = ('edit', 'patch', 'build', 'tests', 'create_machine', 'run_machine', 'task', 'help', 'propose', 'note')
        for action in blocked:
            with self.subTest(action=action):
                with self.assertRaises(PermissionError):
                    self.studios.work_action(self.row, progress, {'action': action, 'args': {}})


if __name__ == '__main__':
    unittest.main()
