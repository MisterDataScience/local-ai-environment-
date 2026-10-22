"""The reconciled controller, durable routing, and serial department scheduling.

Scripted model replies exercise the real queue and SQLite/file persistence. Build
and verification identities in the routing fixture are authored test data; these
checks do not represent compilation, visual acceptance, or real-model playtests.
"""
from concurrent.futures import Future, ThreadPoolExecutor
import json
import sqlite3
import threading
import time
import unittest

import test_studios as fixtures
from studio_store import Store, sha
from studios import Studios


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.StudioTests('test_staff_proposals_add_studio_lead_and_lead_developer')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.staff = self.f.staff()
        self.c, self.s, self.i = self.f.c, self.f.s, self.f.i
        self.pid = self.f.p['project']
        self.lead = self.staff['Studio Lead']

    def workflow(self):
        return self.s.start_workflow(self.i, self.pid, self.lead, 'One game', 'Build a bounded experiment')['id']

    def other_project(self):
        return self.s.ingest(self.i, 'Other game', [('other.c', b'int other;')], dict(kind='fixture'))['project']

    def test_only_one_game_can_reserve_a_studio_even_during_concurrent_start(self):
        other = self.other_project()
        barrier = threading.Barrier(2)
        def start(pid):
            barrier.wait()
            try:
                return self.s.start_workflow(self.i, pid, self.lead, 'Race', 'One experiment')['id']
            except RuntimeError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(start, [self.pid, other]))
        self.assertEqual(sum(bool(result) for result in results), 1)
        with self.s.db() as cx:
            active = self.s.active_workflow(cx, self.i)
        with self.assertRaises(sqlite3.IntegrityError), self.s.db() as cx, cx:
            cx.execute("INSERT INTO studio_workflows SELECT 'duplicate',institution,project,title,goal,phase,state,source,source_sha256,artifacts,history,created,updated FROM studio_workflows WHERE id=?", (active['id'],))

    def test_handoff_waits_for_lead_review_and_revision_preserves_department(self):
        ref = self.workflow()
        assignment = self.s.delegate(self.i, self.pid, self.lead, self.staff['Lead Designer'],
            'Scaffold', '', mode='design', workflow=ref, phase='planning')
        self.s.save_workflow_step(self.i, ref, self.pid, self.staff['Lead Designer'],
            'First scaffold', 'One saved planning decision.', [])
        self.s.finish_delegation(assignment['id'], 'complete', 'Planning handoff.')
        view = self.s.workflow_view(self.i, ref)
        self.assertEqual((view['phase'], view['state']), ('planning', 'awaiting_review'))
        with self.assertRaises(PermissionError):
            self.s.delegate(self.i, self.pid, self.lead, self.staff['Systems designer'],
                'Skip review', '', mode='test-plan', workflow=ref, phase='middle')
        with self.assertRaises(PermissionError):
            self.s.review_workflow_stage(self.i, ref, self.staff['Lead Designer'], 'accept', 'Self-review')
        self.s.review_workflow_stage(self.i, ref, self.lead, 'revise', 'Missing an end state.', 'Add the end state.')
        view = self.s.workflow_view(self.i, ref)
        self.assertEqual((view['phase'], view['state']), ('planning', 'active'))
        self.assertEqual(view['artifacts']['stage_feedback'], 'Add the end state.')
        self.assertEqual(len(view['steps']), 1)

    def test_blocked_production_survives_reopen_and_cancel_releases_its_slot(self):
        ref = self.workflow()
        other = self.other_project()
        with self.s.db() as cx, cx:
            cx.execute("UPDATE studio_workflows SET state='human_review_required' WHERE id=?", (ref,))
        reopened = Store(self.s.root, self.f.connector)
        with self.assertRaises(RuntimeError):
            reopened.start_workflow(self.i, other, self.lead, 'Second game', 'Not yet')
        reopened.cancel_workflow(self.i, ref)
        second = reopened.start_workflow(self.i, other, self.lead, 'Second game', 'Now available')
        self.assertNotEqual(second['id'], ref)
        self.assertEqual(reopened.workflow_view(self.i, ref)['state'], 'cancelled')
        self.assertEqual(reopened.workflow_view(self.i, ref)['history'][-1]['event'], 'cancelled_by_owner')

    def test_legacy_or_queued_work_cannot_run_another_game(self):
        self.c.pause()
        self.workflow()
        other = self.other_project()
        with self.assertRaises(RuntimeError):
            self.c.start(dict(institution=self.i, kind='work', project=other, objective='Bypass the lane'))
        with self.assertRaises(RuntimeError):
            self.s.delegate(self.i, other, self.lead, self.staff['Lead Developer'], 'Bypass', '')

    def test_restart_recovers_waiting_parent_when_specialist_report_is_saved(self):
        self.c.pause()
        ref = self.workflow()
        with self.s.db() as cx, cx:
            cx.execute("UPDATE studio_workflows SET phase='implementation' WHERE id=?", (ref,))
        root = self.s.delegate(self.i, self.pid, self.lead, self.staff['Lead Developer'],
            'Implementation', '', mode='delivery', workflow=ref, phase='implementation')
        child = self.s.delegate(self.i, self.pid, self.staff['Lead Developer'], self.staff['Systems designer'],
            'Specialist', '', mode='analysis', workflow=ref, phase='implementation', parent=root['id'])
        job = self.c.start(dict(institution=self.i, kind='assignment', assignment_id=root['id']))
        self.c.shutdown()
        with self.s.db() as cx, cx:
            cx.execute("UPDATE studio_jobs SET state='waiting' WHERE id=?", (job['id'],))
        self.s.finish_delegation(child['id'], 'complete', 'Saved specialist report before restart.')
        # Normal mode holds inference while startup repairs the durable queue.
        self.f.engine.mode = 'normal'
        restarted = Studios(self.f.engine, self.f.connector)
        self.addCleanup(restarted.shutdown)
        self.f.engine.studios = restarted
        with restarted.store.db() as cx:
            recovered = cx.execute('SELECT state FROM studio_jobs WHERE id=?', (job['id'],)).fetchone()[0]
        self.assertEqual(recovered, 'queued')
        team = restarted.store.team_status(self.i, self.pid, self.staff['Lead Developer'], root['id'])
        self.assertEqual(team['children'][0]['state'], 'complete')
        self.assertIn('before restart', team['children'][0]['result'])

    def test_real_queue_runs_departments_reviews_and_a_serial_specialist_to_closeout(self):
        trace = []
        specialist_seen = []
        def submit(body, studio_turn=None):
            self.assertTrue(self.c.owns(studio_turn))
            self.assertEqual(len(self.c.jobs), 1)
            packet = json.loads(body['messages'][-1]['content'])
            workflow = packet.get('workflow', {})
            ref, phase, state = workflow.get('id'), workflow.get('phase'), workflow.get('state')
            last = packet.get('last_result', {})
            assignment = packet.get('assignment', {})
            mode = assignment.get('mode')
            trace.append((mode or 'manager', phase, state))
            if 'inbox' in packet:
                if state == 'active': action, args = 'workflow_assign', dict(workflow=ref)
                elif state == 'awaiting_review':
                    action, args = 'workflow_review', dict(workflow=ref, decision='accept', review='Reviewed the saved routing fixture handoff.')
                elif state == 'ready_to_close': action, args = 'workflow_close', dict(workflow=ref, summary='Routing fixture reviewed. Native acceptance remains untested.')
                else: action, args = 'done', dict(summary='Department work dispatched or routing fixture closed.')
            elif mode in ('design', 'test-plan') and not workflow.get('checkpoint_counts', {}).get(phase):
                action, args = 'workflow_step', dict(workflow=ref, title=phase+' checkpoint', body='Saved deterministic routing fixture.', evidence=[])
            elif mode == 'lead-developer' and packet['implementation_team']['total'] == 0:
                action, args = 'delegate', dict(resident=self.staff['Systems designer'], title='Implement fixture counter', notes='Change the counter declaration.', mode='implementation')
            elif mode == 'implementation' and not last:
                action, args = 'read', dict(path='game.c')
            elif mode == 'implementation' and 'text' in last:
                action, args = 'edit', dict(path='game.c', text='int counter = 1;\n', expected=last['sha256'])
            elif mode == 'test' and not last:
                action = 'workflow_verify'
                args = dict(workflow=ref, verdict='verified',
                    build=dict(build_id='authored-routing-fixture', source_digest=sha('fixture'), build_status='success', runtime_status='loaded', errors=[], resources={}),
                    tests=[dict(test_id='fixture', description='Authored routing fixture, not runtime acceptance.', seed=1, inputs=[], expected='fixture', actual='fixture', status='passed', evidence=['authored-fixture'])],
                    findings=[], unverified_questions=[], explanation='Authored fixture exercises the verification route only.')
            elif last.get('saved') and not str(last.get('id','')).startswith('studio-verification:'):
                action, args = 'done', dict(summary='Saved fixture handoff; compilation was not run.')
                if mode == 'lead-developer': specialist_seen.extend(packet['implementation_team']['children'])
            else: action, args = 'learning_none', dict(reason='No reusable lesson from this routing fixture.')
            future = Future()
            future.set_result(json.dumps(dict(action=action, args=args)))
            return future
        self.f.engine.submit = submit
        result = self.c.start(dict(institution=self.i, kind='production', project=self.pid, objective='Run the deterministic scheduler fixture.'))
        deadline = time.monotonic()+12
        while self.c.active and time.monotonic() < deadline:
            time.sleep(.01)
        view = self.s.workflow_view(self.i, result['workflow'])
        self.assertFalse(self.c.active, self.s.view(self.i)['jobs'])
        self.assertEqual(view['state'], 'complete', self.s.view(self.i)['jobs'])
        self.assertEqual([h['phase'] for h in view['history'] if h['event']=='stage_accept'], ['planning', 'middle', 'implementation', 'verification'])
        self.assertEqual(self.s.read(self.pid, 'game.c')['text'], 'int counter = 1;')
        self.assertEqual(len(specialist_seen), 1)
        self.assertEqual(specialist_seen[0]['state'], 'complete')
        self.assertTrue(any(item[0]=='implementation' for item in trace))
        self.assertTrue(self.s.recovery_check(self.i, self.pid)['ok'])


if __name__ == '__main__':
    unittest.main()
