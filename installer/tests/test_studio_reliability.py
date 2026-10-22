"""Host permissions and acceptance contracts using authored execution fixtures."""
import base64
import io
import json
import unittest
from unittest.mock import Mock

from PIL import Image
import test_studios as fixtures
from studio_execution_fixture import seed_execution
from studio_roles import WORKFLOW_ROLES
from studio_store import encoded, ident, sha


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.StudioTests('test_staff_proposals_add_studio_lead_and_lead_developer')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.staff = self.f.staff()
        self.c, self.s, self.i = self.f.c, self.f.s, self.f.i
        self.pid = self.f.p['project']
        self.c.pause()
        self.ref = self.s.start_workflow(self.i, self.pid, self.staff['Studio Lead'],
            'Reliability fixture', 'A visible player and a deterministic counter.')['id']

    def assignment(self, phase, live=False):
        role, mode = WORKFLOW_ROLES[phase]
        with self.s.db() as cx, cx:
            cx.execute("UPDATE studio_workflows SET phase=?,state='active' WHERE id=?", (phase, self.ref))
        task = self.s.delegate(self.i, self.pid, self.staff['Studio Lead'], self.staff[role],
            'Check '+phase, '', mode=mode, workflow=self.ref, phase=phase)
        row = dict(id=ident('studio-job'), kind='assignment', institution=self.i, project=self.pid,
            settings=encoded(dict(actor=self.staff[role], actor_title=role, assignment_id=task['id'],
                assignment_mode=task['mode'], workflow=self.ref, workflow_phase=phase)))
        if live:
            job = self.c.start(dict(institution=self.i, kind='assignment', assignment_id=task['id']))
            with self.s.db() as cx, cx:
                cx.execute("UPDATE studio_jobs SET state='running' WHERE id=?", (job['id'],))
                row = dict(cx.execute('SELECT * FROM studio_jobs WHERE id=?', (job['id'],)).fetchone())
        return row, task

    def action(self, row, action, **args):
        return self.c.work_action(row, dict(notes='', last_result={}), dict(action=action, args=args))

    def seed(self, row, task):
        return seed_execution(self.s, self.i, self.pid, self.ref, task['id'], json.loads(row['settings'])['actor'])

    def missing(self, assignment):
        with self.s.db() as cx:
            workflow = cx.execute('SELECT * FROM studio_workflows WHERE id=?', (self.ref,)).fetchone()
            return self.s.workflow_acceptance_missing(cx, workflow, assignment)

    def test_planning_middle_and_playtest_cannot_modify_implementation(self):
        before = self.s.read(self.pid, 'game.c')
        for phase in ('planning', 'middle', 'verification'):
            row, _ = self.assignment(phase)
            denied = ('edit', 'patch', 'delegate')
            if phase != 'verification': denied += ('build', 'tests', 'create_machine', 'run_machine', 'restore')
            for action in denied:
                with self.subTest(phase=phase, action=action), self.assertRaises(PermissionError):
                    self.action(row, action)
        self.assertEqual(self.s.read(self.pid, 'game.c')['sha256'], before['sha256'])

    def test_forged_role_closed_assignment_and_old_workflow_phase_are_denied(self):
        row, task = self.assignment('planning')
        settings = json.loads(row['settings'])
        forged = dict(row, settings=encoded(dict(settings, assignment_mode='lead-developer')))
        with self.assertRaises(PermissionError): self.action(forged, 'edit')
        with self.s.db() as cx, cx:
            cx.execute("UPDATE studio_workflows SET phase='implementation' WHERE id=?", (self.ref,))
        with self.assertRaises(PermissionError): self.action(row, 'source_tree', source=self.f.p['source'])
        implementation, task = self.assignment('implementation')
        self.s.finish_delegation(task['id'], 'complete', 'Saved report.')
        with self.assertRaises(PermissionError): self.action(implementation, 'edit')

    def test_unassigned_legacy_session_cannot_gain_writer_permissions(self):
        row=dict(id='legacy-fixture',kind='work',institution=self.i,project=self.pid,
            settings=encoded(dict(actor=self.staff['Lead Designer'])))
        with self.assertRaises(PermissionError):self.action(row,'edit')

    def test_planning_and_middle_need_saved_checkpoints_before_handoff(self):
        for phase in ('planning','middle'):
            row, task = self.assignment(phase)
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, 'durable'):
                self.s.finish_delegation(task['id'], 'complete', 'Unsupported summary only.')
            self.action(row, 'workflow_step', workflow=self.ref, title='Saved '+phase, body='A bounded fixture checkpoint.', evidence=[])
            self.s.finish_delegation(task['id'], 'complete', 'Checkpoint saved.')
            self.assertEqual(self.s.workflow_view(self.i,self.ref)['state'],'awaiting_review')

    def test_other_project_builds_machines_and_saved_states_are_rejected(self):
        row, _ = self.assignment('verification')
        other = self.s.ingest(self.i, 'Other source', [('other.c', b'int other;')], dict(kind='fixture'))['project']
        self.c.workbench.cartridge = lambda *args: ({}, dict(project=other))
        for action in ('tests', 'create_machine'):
            with self.subTest(action=action), self.assertRaises(PermissionError): self.action(row, action, build='other-build')
        machine = ident('machine')
        self.c.workbench.machines[machine] = dict(institution=self.i, project=other, build='other-build')
        for action in ('run_machine', 'observe', 'snapshot', 'reset', 'drop', 'inspect'):
            with self.subTest(action=action), self.assertRaises(PermissionError): self.action(row, action, machine=machine)
        saved = ident('machine')
        path = self.s.directory/self.i.split(':')[1]/'machines'/(saved.split(':')[1]+'.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded(dict(meta=dict(project=other, build='other-build'), state=dict(version=1))))
        with self.assertRaises(PermissionError): self.action(row, 'restore', saved=saved)

    def test_malformed_json_and_missing_file_return_to_same_agent_for_correction(self):
        row, task = self.assignment('implementation')
        self.f.engine.responses = ['invalid JSON', encoded(dict(action='read', args=dict(path='missing.c'))),
            encoded(dict(action='read', args=dict(path='game.c'))),
            encoded(dict(action='learning_none', args=dict(reason='Correction fixture only.'))),
            encoded(dict(action='done', args=dict(summary='Read the actual file after correcting both errors.')))]
        job = self.c.start(dict(institution=self.i, kind='assignment', assignment_id=task['id']))
        self.c.resume(job['id'])
        result = self.f.wait(job['id'])
        self.assertEqual(result['state'], 'complete', result['reason'])
        errors = [event for event in self.s.view(self.i)['events'] if event['job']==job['id'] and event['kind']=='tool_error']
        self.assertEqual(len(errors), 2)
        self.assertEqual({event['body']['error_type'] for event in errors},{'JSONDecodeError','FileNotFoundError'})
        self.assertTrue(all(event['body']['retryable'] for event in errors))
        self.assertTrue(all('read' in event['body']['allowed_actions'] for event in errors))
        self.assertTrue(any('Correct the tool arguments' in call['messages'][-1]['content'] for call in self.f.engine.calls))

    def test_failed_build_can_be_corrected_in_the_same_assignment(self):
        _, task = self.assignment('implementation')
        before = self.s.read(self.pid, 'game.c')
        self.c.workbench.build = Mock(side_effect=[dict(id='failed-fixture', state='failed', diagnostics='Authored missing declaration.'), dict(id='fixed-fixture', state='passed')])
        self.f.engine.responses = [encoded(dict(action='build', args={})),
            encoded(dict(action='read', args=dict(path='game.c'))),
            encoded(dict(action='edit', args=dict(path='game.c', expected=before['sha256'], text='int corrected_counter;'))),
            encoded(dict(action='build', args={})),
            encoded(dict(action='learning_none', args=dict(reason='Compiler-result fixture, not native execution.'))),
            encoded(dict(action='done', args=dict(summary='Corrected the authored build failure.')))]
        job = self.c.start(dict(institution=self.i, kind='assignment', assignment_id=task['id']))
        self.c.resume(job['id'])
        result = self.f.wait(job['id'])
        self.assertEqual(result['state'], 'complete', result['reason'])
        self.assertEqual(self.c.workbench.build.call_count, 2)
        self.assertEqual(self.s.read(self.pid, 'game.c')['text'], 'int corrected_counter;')

    def test_fabricated_verification_and_receipt_action_cannot_pass(self):
        row, task = self.assignment('verification')
        # Create a valid report shape, then remove the host receipts it depends on.
        fixture = self.seed(row, task)
        with self.s.db() as cx, cx:
            wf = cx.execute('SELECT artifacts FROM studio_workflows WHERE id=?', (self.ref,)).fetchone()
            artifacts = json.loads(wf[0]);artifacts.pop('acceptance')
            cx.execute('UPDATE studio_workflows SET artifacts=? WHERE id=?', (encoded(artifacts), self.ref))
        with self.assertRaisesRegex(ValueError, 'host-recorded execution'):
            self.action(row, 'workflow_verify', **fixture['report'])
        with self.assertRaises(PermissionError): self.action(row, 'record_workflow_execution', **fixture)

    def test_stale_build_empty_assertions_and_different_machine_fail_acceptance(self):
        row, task = self.assignment('verification')
        fixture = self.seed(row, task)
        self.assertEqual(self.missing(task['id']), [])
        visual = dict(fixture['visual'], machine=ident('machine'))
        self.s.record_workflow_execution(self.i, self.ref, task['id'], self.staff['Playtest reviewer'], 'visual', visual)
        self.assertTrue(any('same machine' in reason for reason in self.missing(task['id'])))
        self.s.record_workflow_execution(self.i, self.ref, task['id'], self.staff['Playtest reviewer'], 'tests', dict(fixture['tests'], tests=[]))
        self.assertTrue(any('authored assertions' in reason for reason in self.missing(task['id'])))
        current = self.s.read(self.pid, 'game.c')
        self.s.edit(self.pid, 'game.c', 'int changed_after_tests;', current['sha256'])
        self.assertTrue(any('current working-copy' in reason for reason in self.missing(task['id'])))

    def prepare_inspection(self):
        row, task = self.assignment('verification', live=True)
        fixture = self.seed(row, task)
        run = fixture['run'];machine = run['machine']
        self.c.workbench.machines[machine] = dict(institution=self.i, project=self.pid, build=run['build'])
        output = io.BytesIO();Image.new('RGBA', (320, 180), (10, 20, 30, 255)).save(output, format='PNG')
        observation = dict(png=base64.b64encode(output.getvalue()).decode(), metrics={},
            **{key:run[key] for key in ('ticks', 'evidence', 'screen_sha256')})
        self.c.workbench.machine = lambda *args, **kwargs: observation
        return row, task, fixture, observation

    def test_headless_inspection_sends_a_real_png_and_records_matching_frame(self):
        row, task, fixture, observation = self.prepare_inspection()
        seen = {}
        def infer(jid, system, packet, image=None):
            seen.update(image=image, objective=packet['objective'])
            return encoded(dict(status='pass', review='Authored image-review response.', issues=[]))
        self.c.infer = infer
        result, _ = self.action(row, 'inspect', machine=fixture['run']['machine'], question='Is the visible screen coherent?')
        self.assertEqual(seen['image'], observation['png'])
        self.assertIn('visible player', seen['objective'])
        self.assertEqual(result['visual_review']['status'], 'pass')
        self.assertEqual(self.missing(task['id']), [])

    def test_unavailable_vision_stays_open_for_human_review(self):
        row, task, fixture, _ = self.prepare_inspection()
        def unavailable(*args, **kwargs): raise ValueError('Installed model has no vision capability')
        self.c.infer = unavailable
        result, _ = self.action(row, 'inspect', machine=fixture['run']['machine'], question='Inspect the frame.')
        self.assertEqual(result['visual_review']['status'], 'unavailable')
        with self.assertRaises(ValueError): self.action(row, 'workflow_verify', **fixture['report'])
        self.action(row, 'workflow_verify', **dict(fixture['report'], verdict='human_review_required'))
        self.s.finish_delegation(task['id'], 'complete', 'Image review requires a capable model or human.')
        self.s.review_workflow_stage(self.i, self.ref, self.staff['Studio Lead'], 'accept', 'Keep the unresolved visual review open.')
        self.assertEqual(self.s.workflow_view(self.i, self.ref)['state'], 'human_review_required')

    def test_invalid_png_cannot_reuse_a_previous_visual_pass(self):
        row,task,fixture,observation=self.prepare_inspection()
        observation['png']=base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'not a complete image').decode()
        self.c.infer=Mock(side_effect=AssertionError('Invalid frames must not reach inference'))
        with self.assertRaises(OSError):self.action(row,'inspect',machine=fixture['run']['machine'],question='Inspect.')
        self.c.infer.assert_not_called()
        self.assertTrue(self.missing(task['id']))

    def test_new_playtest_assignment_cannot_reuse_another_assignments_receipts(self):
        row,task=self.assignment('verification')
        fixture=self.seed(row,task)
        self.s.finish_delegation(task['id'],'blocked','Start another independent review.')
        replacement,new_task=self.assignment('verification')
        with self.assertRaisesRegex(ValueError,'this independent Playtest assignment'):
            self.action(replacement,'workflow_verify',**fixture['report'])

    def test_zero_input_and_unverified_questions_cannot_be_declared_verified(self):
        row,task=self.assignment('verification')
        fixture=self.seed(row,task)
        with self.assertRaises(ValueError):
            self.action(row,'workflow_verify',**dict(fixture['report'],unverified_questions=['Is the required player visible?']))
        self.s.record_workflow_execution(self.i,self.ref,task['id'],self.staff['Playtest reviewer'],'run',dict(fixture['run'],steps=0))
        self.assertTrue(any('input run' in reason for reason in self.missing(task['id'])))

    def test_pause_during_inspection_cannot_publish_a_late_pass(self):
        row, task, fixture, _ = self.prepare_inspection()
        def paused(*args, **kwargs):
            with self.s.db() as cx, cx: cx.execute("UPDATE studio_jobs SET state='paused' WHERE id=?", (row['id'],))
            return encoded(dict(status='pass', review='Late response must be ignored.', issues=[]))
        self.c.infer = paused
        with self.assertRaises(PermissionError): self.action(row, 'inspect', machine=fixture['run']['machine'], question='Inspect the frame.')
        self.assertTrue(self.missing(task['id']))

    def test_failed_run_cannot_keep_an_earlier_visual_acceptance(self):
        row,task,fixture,_=self.prepare_inspection()
        self.c.workbench.machine=Mock(side_effect=RuntimeError('Authored runtime trap'))
        with self.assertRaisesRegex(RuntimeError,'trap'):
            self.action(row,'run_machine',machine=fixture['run']['machine'],steps=1,buttons=8)
        self.assertTrue(any('input run' in reason for reason in self.missing(task['id'])))

    def test_visible_failure_returns_to_implementation_after_lead_review(self):
        row, task, fixture, _ = self.prepare_inspection()
        self.c.infer = lambda *args, **kwargs: encoded(dict(status='revise',review='The authored fixture has no visible player.',issues=['Missing player']))
        self.action(row,'inspect',machine=fixture['run']['machine'],question='Check player visibility.')
        with self.assertRaises(ValueError): self.action(row,'workflow_verify',**fixture['report'])
        self.action(row,'workflow_verify',**dict(fixture['report'],verdict='return_to_implementation'))
        self.s.finish_delegation(task['id'],'complete','Return the visible player failure.')
        self.assertEqual(self.s.workflow_view(self.i,self.ref)['state'],'awaiting_review')
        self.s.review_workflow_stage(self.i,self.ref,self.staff['Studio Lead'],'accept','Fix the visible failure before another independent test.')
        view=self.s.workflow_view(self.i,self.ref)
        self.assertEqual((view['phase'],view['state']),('implementation','active'))

    def test_final_closeout_rechecks_source_after_verified_report(self):
        row, task = self.assignment('verification')
        fixture = self.seed(row, task)
        self.action(row, 'workflow_verify', **fixture['report'])
        self.s.finish_delegation(task['id'], 'complete', 'Fixture verified.')
        self.s.review_workflow_stage(self.i, self.ref, self.staff['Studio Lead'], 'accept', 'Checked the host receipts.')
        before = self.s.read(self.pid, 'game.c')
        self.s.edit(self.pid, 'game.c', 'int changed_before_closeout;', before['sha256'])
        with self.assertRaisesRegex(ValueError, 'current working-copy'):
            self.s.close_workflow(self.i, self.ref, self.staff['Studio Lead'], 'Must not close stale evidence.')

    def test_vacuous_cartridge_tests_are_rejected_before_execution(self):
        workbench = self.c.workbench
        workbench.create = Mock(side_effect=AssertionError('Invalid tests must not execute'))
        for tests in ([], [{}], [dict(name='empty', expect_metrics={})], [dict(name='a', expect_metrics={'0':1})]*2):
            workbench.cartridge = lambda *args: (dict(tests=tests), {})
            with self.subTest(tests=tests), self.assertRaises(ValueError): workbench.tests(self.i, 'fixture')
        workbench.create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
