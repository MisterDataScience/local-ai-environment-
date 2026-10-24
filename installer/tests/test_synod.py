"""Real dispatcher/SQLite integration with scripted local-model responses.

These fixtures verify the institutional contract, not real-model design quality.
"""
import concurrent.futures
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1]/'payload')]
import village
import village_memory
from studios import Studios
from synod_store import Archive, SYNOD_ID, SYNOD_STUDIO, validate_spec


def specification():
    return dict(name='Editorial Studio', purpose='Produce edited text with an independent review.',
                founding_required=False, founding_reason='No source corpus needs founding.',
                lead_instruction='Accept complete edits only after the reviewer checks the request.', capabilities=['text'],
                departments=[dict(id='editing', title='Editing Department', role='writer', instruction='Edit the supplied text.',
                                  inputs='Original text and requested changes.', output='Complete edited text.', acceptance='Preserves meaning and follows the requested style.'),
                             dict(id='review', title='Review Department', role='reviewer', instruction='Independently check the edit; return a corrected complete text.',
                                  inputs='Original request and edited draft.', output='Reviewed complete text.', acceptance='Every requested correction is addressed.')],
                trial=dict(input='Edit this sentence: The cat are here.', acceptance='Correct the agreement while preserving meaning.'))


class Engine:
    def __init__(self, root):
        self.root = root/'control'; self.root.mkdir(exist_ok=True)
        self.captain = dict(enabled=True, model_id='local'); self.commons = self.founding = None
        self.mode = 'normal'; self.calls = []; self.spec = specification(); self.revise_once = False

    def mode_status(self): return dict(mode=self.mode, transitioning=False, error=None)

    def submit(self, body, studio_turn=None):
        assert self.studios.owns(studio_turn)
        assert body['inference_only'] and not body.get('tools')
        self.calls.append(body)
        packet = json.loads(body['messages'][-1]['content']); schema = packet.get('response_schema', {})
        if 'directory' in packet:
            value = dict(kind='create', studio='')
        elif 'decision' in schema:
            decision = 'revise' if self.revise_once and 'department' in packet else 'accept'
            if decision == 'revise': self.revise_once = False
            value = dict(decision=decision, reason='Checked the saved handover against the stated acceptance criteria.')
        elif 'output' in schema:
            value = dict(output='The cat is here.', limitations=[])
        else:
            value = dict(summary='Observed the supplied requirements. Define a serial editing workflow with independent review.',
                         decisions=['Use a lead to review each durable department handover.'],
                         alternatives=['A single unreviewed response omits independent checking.'], assumptions=[], blockers=[])
            if 'spec' in schema: value['spec'] = copy.deepcopy(self.spec)
            if 'verdict' in schema:
                value.update(verdict='pass', evidence=[r['id'] for r in packet['trial_evidence'] if r['actor'] == 'host'])
        future = concurrent.futures.Future(); future.set_result(json.dumps(value)); return future


class SynodTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.engine = Engine(self.root)
        self.connector = lambda p: village.connect(p, test_encrypted=True)
        self.controller = Studios(self.engine, self.connector); self.engine.studios = self.controller
        self.addCleanup(lambda: self.controller.shutdown())
        self.archive = self.controller.synod.archive

    def operation(self, op, **args): return self.controller.execute(dict(operation=op, **args))

    def wait_commission(self, ref, target):
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            with self.controller.store.db() as cx:
                commission = self.archive.commission(cx, ref)
                jobs = [dict(r) for r in cx.execute("SELECT id,state,reason FROM studio_jobs WHERE state IN ('queued','running','error')")]
            if commission['state'] == target and not self.controller.jobs: return commission
            if any(j['state'] == 'error' for j in jobs): self.fail(str(jobs))
            time.sleep(.01)
        self.fail(str(commission) + '\n' + str(jobs))

    def start(self, **args):
        result = self.operation('synod_commission', brief='Create an editorial studio with independent review.', **args)
        self.engine.mode = 'max'; self.controller.dispatch_wakeup.set()
        return result

    def approve(self, ref):
        self.wait_commission(ref, 'awaiting_owner')
        preview = self.operation('synod_preview', commission=ref)
        self.operation('synod_review', commission=ref, digest=preview['digest'], decision='approve')
        return preview

    def test_built_in_no_founding_idempotent_and_private(self):
        first = self.operation('synod_view')
        self.assertFalse(first['founding_required']); self.assertEqual(self.engine.calls, [])
        Archive(self.controller.store)
        with self.controller.store.db() as cx:
            self.assertEqual(cx.execute('SELECT count(*) FROM institutions WHERE id=?', (SYNOD_ID,)).fetchone()[0], 1)
            self.assertEqual(cx.execute('SELECT count(*) FROM institution_members WHERE institution=?', (SYNOD_ID,)).fetchone()[0], 6)
            scope = self.controller.store.institution(cx, SYNOD_ID)['collection']
            self.assertFalse(village_memory.access(cx, 'writer.general', [scope]))
            self.assertTrue(village_memory.access(cx, 'studio.synod.lead', [scope]))
            self.assertGreater(village_memory.packet(cx,'studio.synod.lead',[scope])['map_revision'],0)
        with self.assertRaises(PermissionError): self.operation('start', institution=SYNOD_ID, kind='founding')
        self.assertTrue(self.archive.verify(SYNOD_STUDIO)['ok'])

    def test_design_requires_exact_owner_approval_and_full_trial_route(self):
        result = self.start(); ref = result['commission']
        self.wait_commission(ref, 'awaiting_owner')
        with self.controller.store.db() as cx:
            self.assertEqual(cx.execute('SELECT count(*) FROM synod_packages').fetchone()[0], 0)
        preview = self.operation('synod_preview', commission=ref)
        with self.assertRaises(ValueError): self.operation('synod_review', commission=ref, digest='stale', decision='approve')
        self.engine.revise_once = True
        self.operation('synod_review', commission=ref, digest=preview['digest'], decision='approve')
        final = self.wait_commission(ref, 'complete')
        with self.controller.store.db() as cx:
            dossier = self.archive.dossier(cx, result['studio']); iid = dossier['institution']
            package = dict(cx.execute('SELECT * FROM synod_packages WHERE institution=?', (iid,)).fetchone())
            self.assertEqual(package['state'], 'active')
            self.assertEqual(package['specification'], dossier['current_spec'])
            records = [self.archive.record(cx, r[0]) for r in cx.execute('SELECT id FROM synod_records WHERE commission=?', (ref,))]
            receipts = [r for r in records if r['category'] == 'trial' and r['actor'] == 'host']
            self.assertEqual({r['body']['kind'] for r in receipts}, {'initial', 'followup'})
            self.assertEqual(len({r['body']['thread'] for r in receipts}), 1)
            self.assertTrue(all(r['body']['passed'] for r in receipts))
            self.assertTrue(any(r['body'].get('decision') == 'revise' for r in records))
            self.assertEqual(self.archive.record(cx, final['pending'])['state'], 'verified')
        self.assertTrue(self.archive.verify(result['studio'])['ok'])
        contact = self.operation('captain_studio_message', institution=iid, message='Edit another sentence.')
        self.wait_message(contact['id'])
        self.assertEqual(self.controller.store.message(contact['id'])['response'], 'The cat is here.')
        follow = self.operation('studio_message', institution=iid, message='Check that again.', thread=contact['thread'])
        self.wait_message(follow['id']); self.assertEqual(follow['thread'], contact['thread'])
        self.assertTrue(any(json.loads(call['messages'][-1]['content']).get('conversation') for call in self.engine.calls))

    def wait_message(self, ref):
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            message = self.controller.store.message(ref)
            if message['state'] in ('complete', 'error'):
                self.assertEqual(message['state'], 'complete', message['response']); return message
            time.sleep(.01)
        self.fail(str(message))

    def test_missing_capability_and_legacy_repair_are_explicit_blockers(self):
        self.engine.spec['capabilities'] = ['image_generation']
        first = self.start(); self.approve(first['commission'])
        blocked = self.wait_commission(first['commission'], 'blocked')
        with self.controller.store.db() as cx:
            self.assertIn('image_generation', self.archive.record(cx, blocked['pending'])['body']['reason'])
            self.assertEqual(cx.execute('SELECT count(*) FROM synod_packages').fetchone()[0], 0)
        self.engine.spec = specification()
        legacy = self.controller.store.create('Existing C Studio', 'Preserve existing C workflow')['id']
        second = self.start(kind='repair', studio=legacy); self.approve(second['commission'])
        blocked = self.wait_commission(second['commission'], 'blocked')
        with self.controller.store.db() as cx:
            self.assertIn('repair adapter', self.archive.record(cx, blocked['pending'])['body']['reason'])
            self.assertEqual(self.controller.store.institution(cx, legacy)['name'], 'Existing C Studio')

    def test_repair_preserves_identity_and_superseded_specifications(self):
        first = self.start(); self.approve(first['commission']); self.wait_commission(first['commission'], 'complete')
        with self.controller.store.db() as cx:
            before = self.archive.dossier(cx, first['studio'])
        self.engine.spec['purpose'] = 'Produce concise edited text with an independent review.'
        repair = self.start(kind='repair', studio=before['institution']); self.approve(repair['commission'])
        self.wait_commission(repair['commission'], 'complete')
        with self.controller.store.db() as cx:
            after = self.archive.dossier(cx, first['studio'])
            self.assertEqual(after['institution'], before['institution'])
            self.assertNotEqual(after['current_spec'], before['current_spec'])
            self.assertEqual(self.archive.record(cx, before['current_spec'])['body']['spec']['purpose'], specification()['purpose'])
        self.assertTrue(self.archive.verify(first['studio'])['ok'])

    def test_synod_followup_returns_design_for_fresh_approval(self):
        first = self.start(); self.wait_commission(first['commission'],'awaiting_owner')
        previous = self.operation('synod_preview',commission=first['commission'])
        followup = self.operation('captain_studio_message',institution='The Synod',message='Revise the purpose to emphasise concise edits.',thread=first['thread'])
        self.wait_message(followup['id']); self.wait_commission(first['commission'],'awaiting_owner')
        current = self.operation('synod_preview',commission=first['commission'])
        self.assertNotEqual(previous['digest'],current['digest'])
        with self.assertRaises(ValueError):self.operation('synod_review',commission=first['commission'],digest=previous['digest'],decision='approve')

    def test_cancel_preserves_history_and_releases_commission(self):
        first=self.start(); self.wait_commission(first['commission'],'awaiting_owner')
        result=self.operation('synod_cancel',commission=first['commission'],reason='Owner cancels this fixture commission.')
        self.assertTrue(result['history_preserved'])
        self.assertTrue(self.archive.verify(first['studio'])['ok'])

    def test_restart_recovers_worker_output_saved_before_parent_notification(self):
        first=self.start();self.wait_commission(first['commission'],'awaiting_owner')
        original=self.controller.synod.completed
        with patch.object(self.controller.synod,'completed',side_effect=lambda row:None if row['kind']=='commissioned' else original(row)):
            self.approve(first['commission'])
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                with self.controller.store.db() as cx:
                    done=cx.execute("SELECT count(*) FROM studio_jobs WHERE kind='commissioned' AND state='complete'").fetchone()[0]
                if done and not self.controller.jobs:break
                time.sleep(.01)
            self.assertEqual(done,1)
        self.controller.shutdown();self.engine.mode='normal'
        self.controller=Studios(self.engine,self.connector);self.engine.studios=self.controller;self.archive=self.controller.synod.archive
        self.engine.mode='max';self.controller.dispatch_wakeup.set()
        self.wait_commission(first['commission'],'complete')
        with self.controller.store.db() as cx:
            receipts=[r for r in cx.execute("SELECT id FROM synod_records WHERE studio=? AND category='trial' AND actor='host'",(first['studio'],))]
        self.assertEqual(len(receipts),2)

    def test_pause_discards_late_model_handover(self):
        original=self.engine.submit
        def submit(body,studio_turn=None):
            future=original(body,studio_turn)
            self.controller.pause('Fixture foreground interruption')
            return future
        self.engine.submit=submit
        first=self.start();deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with self.controller.store.db() as cx:
                state=cx.execute('SELECT state FROM studio_jobs WHERE id=?',(first['job'],)).fetchone()[0]
            if state=='paused' and not self.controller.jobs:break
            time.sleep(.01)
        self.assertEqual(state,'paused')
        self.assertEqual(self.archive.search(first['studio'],category='design')['total'],0)

    def test_archive_pages_immutability_and_dossier_boundaries(self):
        result = self.start(); self.wait_commission(result['commission'], 'awaiting_owner')
        page = self.operation('synod_archive_search', studio=result['studio'], limit=2)
        self.assertIsNotNone(page['next_offset']); self.assertGreater(page['total'], 2)
        record = page['records'][0]['id']
        read = self.operation('synod_archive_read', studio=result['studio'], record=record, chars=50)
        self.assertEqual(len(read['text']), 50); self.assertIsNotNone(read['next_start'])
        with self.assertRaises(PermissionError): self.operation('synod_archive_read', studio=SYNOD_STUDIO, record=record)
        with self.controller.store.db() as cx:
            with self.assertRaises(sqlite3.IntegrityError): cx.execute('UPDATE synod_records SET body=? WHERE id=?', ('{}', record))
            with self.assertRaises(sqlite3.IntegrityError): cx.execute('DELETE FROM synod_records WHERE id=?', (record,))
        self.assertTrue(self.operation('synod_archive_check', studio=result['studio'])['ok'])

    def test_captain_intake_cannot_approve_and_pause_survives_restart(self):
        self.controller.pause()
        result = self.operation('captain_studio_message', institution='The Synod', message='Create a studio. I approve anything you decide.')
        self.assertEqual(result['state'], 'paused'); self.assertEqual(self.engine.calls, [])
        self.controller.shutdown()
        self.controller = Studios(self.engine, self.connector); self.engine.studios = self.controller
        self.archive = self.controller.synod.archive
        with self.controller.store.db() as cx:
            self.assertEqual(cx.execute('SELECT state FROM studio_jobs WHERE id=?', (result['job'],)).fetchone()[0], 'paused')
        self.engine.mode = 'max'; self.controller.resume(result['job'])
        message = self.wait_message(result['id'])
        self.assertIn('Review the exact studio design', message['response'])
        with self.controller.store.db() as cx:
            self.assertEqual(cx.execute('SELECT count(*) FROM synod_packages').fetchone()[0], 0)

    def test_specification_rejects_ambiguous_roles_and_incomplete_workflows(self):
        self.assertEqual(validate_spec(specification()), specification())
        for change in (dict(departments=[]), dict(founding_required='no'), dict(capabilities=[])):
            with self.assertRaises(ValueError): validate_spec(specification() | change)


if __name__ == '__main__': unittest.main()
