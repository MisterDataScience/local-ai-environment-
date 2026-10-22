"""Bounded studio context and recoverable detail, without native runtime fixtures."""
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import test_studios as fixtures
from studio_store import encoded, ident, sha


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.StudioTests('test_staff_proposals_add_studio_lead_and_lead_developer')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.staff=self.f.staff();self.c=self.f.c;self.s=self.f.s;self.i=self.f.i;self.pid=self.f.p['project']
        self.c.pause()
        self.row=dict(id=ident('studio-job'),institution=self.i,project=self.pid,kind='work',
            settings=encoded(dict(actor=self.staff['Lead Designer'],objective='Check a bounded packet.')))
        self.progress=dict(notes='',last_result={})

    def action(self,action,**args):
        return self.c.work_action(self.row,self.progress,dict(action=action,args=args))[0]

    def test_tree_pages_hash_only_selected_files_and_reuse_unchanged_digests(self):
        root=self.s.path(self.pid)
        for n in range(20):(root/f'file{n:02}.c').write_text('int counter;')
        original=Path.read_bytes;reads=[]
        def read(path):
            if path.parent==root:reads.append(path.name)
            return original(path)
        with patch.object(Path,'read_bytes',read):
            page=self.s.tree_page(self.pid,0,3)
            self.assertEqual(len(reads),3)
            self.assertEqual(self.s.tree_page(self.pid,0,3),page)
            self.assertEqual(len(reads),3)
            file=root/page['files'][0]['path'];file.write_text('changed text')
            changed=self.s.tree_page(self.pid,0,3)
            self.assertEqual(len(reads),4)
        self.assertNotEqual(changed['files'][0]['sha256'],page['files'][0]['sha256'])
        self.assertTrue(page['truncated']);self.assertEqual(page['total'],22)
        self.assertEqual(changed['files'][0]['sha256'],sha('changed text'))

    def test_tree_listing_detects_replacement_new_files_and_links(self):
        before=self.s.tree_page(self.pid)
        root=self.s.path(self.pid);file=root/'game.c'
        replacement=root/'replace.c';replacement.write_bytes(file.read_bytes());replacement.replace(file)
        (root/'added.c').write_text('new')
        self.assertEqual(self.s.tree_page(self.pid)['total'],before['total']+1)
        (root/'linked.c').symlink_to(file)
        with self.assertRaises(PermissionError):self.s.tree_page(self.pid)

    def test_source_tree_pages_cover_archive_and_enforce_scope(self):
        imported=self.s.ingest(self.i,'Archive page fixture',[(f'file{n:03}.c',b'int x;') for n in range(27)],dict(kind='fixture'))
        names=[];offset=0
        while True:
            page=self.action('source_tree',source=imported['source'],offset=offset,limit=7)
            names.extend(row['path'] for row in page['files'])
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual(names,[f'file{n:03}.c' for n in range(27)])
        self.assertFalse(page['truncated']);self.assertEqual(page['total'],27)
        other=self.s.create('Other studio','Boundary fixture')['id']
        private=self.s.ingest(other,'Private',[('secret.c',b'secret')],dict(kind='fixture'))
        with self.assertRaises(PermissionError):self.action('source_tree',source=private['source'])
        for args in (dict(offset=-1),dict(limit=0),dict(limit=True),dict(limit=101)):
            with self.assertRaises(ValueError):self.action('source_tree',source=imported['source'],**args)

    def test_large_unicode_results_page_losslessly_and_survive_saved_progress(self):
        original=dict(saved=True,id='receipt',text='漢𐐀é'*3000)
        summary=self.c.page_result(self.progress,original)
        self.assertLess(len(encoded(summary).encode()),1500)
        self.progress=json.loads(encoded(self.progress));parts=[];start=0
        while True:
            page=self.action('result_read',result_id=summary['result_id'],start=start,chars=2000)
            self.assertLessEqual(len(page['text'].encode()),2000)
            self.assertEqual(self.c.page_result(self.progress,page),page)
            parts.append(page['text'])
            if page['next_start'] is None:break
            self.assertGreater(page['next_start'],start);start=page['next_start']
        self.assertEqual(json.loads(''.join(parts)),original)
        self.assertEqual(self.progress['result_detail']['id'],summary['result_id'])

    def test_small_results_do_not_expire_large_result_but_new_large_result_does(self):
        old=self.c.page_result(self.progress,dict(text='x'*8000,parent='parent-assignment',independent_worker=True))
        self.assertEqual(old['parent'],'parent-assignment');self.assertTrue(old['independent_worker'])
        self.c.page_result(self.progress,dict(saved=True))
        self.assertIn('text',self.action('result_read',result_id=old['result_id']))
        new=self.c.page_result(self.progress,dict(text='y'*8000))
        with self.assertRaises(ValueError):self.action('result_read',result_id=old['result_id'])
        for args in (dict(start=-1),dict(chars=0),dict(chars=2001),dict(chars=True)):
            with self.assertRaises(ValueError):self.action('result_read',result_id=new['result_id'],**args)

    def test_work_packet_keeps_large_result_pointer_and_explicit_tree_total(self):
        original=dict(text='readable source '*1000)
        self.progress['last_result']=original
        packet=self.c.work_packet(self.row,self.progress)
        self.assertIn('result_id',packet['last_result'])
        self.assertEqual(json.loads(self.progress['result_detail']['text']),original)
        self.assertEqual(packet['file_page']['total'],2)
        self.assertNotIn('result_detail',packet)

    def test_compact_checkpoints_keep_original_digest_and_full_read_available(self):
        lead=self.staff['Studio Lead'];designer=self.staff['Lead Designer']
        ref=self.s.start_workflow(self.i,self.pid,lead,'Check previews','Read complete saved checkpoint.')['id']
        self.s.delegate(self.i,self.pid,lead,designer,'Planning','',mode='design',workflow=ref,phase='planning')
        evidence=self.action('source',source=self.f.p['source'],path='game.c')
        citation=dict(source=self.f.p['source'],path='game.c',digest=evidence['digest'],quote='int counter;')
        step=self.s.save_workflow_step(self.i,ref,self.pid,designer,'Complete checkpoint','x'*1500,[citation])
        compact=self.s.workflow_view(self.i,ref,compact=True)['steps'][0]
        self.assertEqual(compact['body_chars'],1500);self.assertEqual(len(compact['body']),500)
        self.assertEqual(compact['digest'],step['digest'])
        complete=self.action('workflow_read',workflow=ref,phase='planning')
        self.assertEqual(complete['steps'][0]['body'],'x'*1500)
        self.assertEqual(len(complete['steps'][0]['evidence'])>0,True)

    def test_workflow_artifact_is_retrievable_and_cross_project_reads_rejected(self):
        ref=self.s.start_workflow(self.i,self.pid,self.staff['Studio Lead'],'Report paging','Read a handoff.')['id']
        value=dict(summary='x'*5000,assignment='saved-assignment')
        with self.s.db() as cx,cx:cx.execute('UPDATE studio_workflows SET artifacts=? WHERE id=?',(encoded(dict(pending_handoff=value)),ref))
        result=self.action('workflow_read',workflow=ref,artifact='pending_handoff')
        full=json.loads(self.progress['result_detail']['text'])
        self.assertEqual(full['value'],value);self.assertIn('result_id',result)
        with self.assertRaises(ValueError):self.action('workflow_read',workflow=ref,artifact='unknown')
        second=self.s.ingest(self.i,'Other project',[('x.c',b'int x;')],dict(kind='fixture'))
        self.row['project']=second['project']
        with self.assertRaises(PermissionError):self.action('workflow_read',workflow=ref,artifact='pending_handoff')

    def test_evidence_summary_decodes_only_recent_records_and_reuses_cache(self):
        bid=ident('build');root=self.s.directory/self.i.split(':')[1]/'builds'/bid.split(':')[1]/'evidence';root.mkdir(parents=True)
        with self.s.db() as cx,cx:cx.execute('INSERT INTO studio_builds VALUES(?,?,?,?,?,?,?)',(bid,self.pid,'digest','cartridge','passed','{}',0))
        for n in range(12):
            path=root/(f'{n:032x}.json')
            path.write_text(encoded(dict(id='evidence:'+f'{n:032x}',project=self.pid,build=bid,input_sequence=[dict(steps=1)]*100,assertions=[],findings=[],screenshot_png_base64='large picture'*1000)))
            os.utime(path,ns=(1_000_000_000+n,1_000_000_000+n))
        original=Path.read_text;reads=[]
        def read(path,*args,**kwargs):
            if path.parent==root:reads.append(path.name)
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read):
            summaries=self.c.workbench.recent_evidence(self.i,self.pid,limit=3,summary_only=True)
            self.assertEqual(len(reads),3)
            self.assertEqual(self.c.workbench.recent_evidence(self.i,self.pid,limit=3,summary_only=True),summaries)
            self.assertEqual(len(reads),3)
        self.assertEqual(summaries[0]['id'],'evidence:'+f'{11:032x}')
        self.assertEqual(summaries[0]['input_count'],100)
        self.assertNotIn('input_sequence',summaries[0]);self.assertNotIn('screenshot_png_base64',summaries[0])
        self.assertLess(len(encoded(summaries).encode()),1500)
        detail=self.c.workbench.evidence_detail(self.i,self.pid,summaries[0]['id'],start=90,limit=10)
        self.assertEqual(len(detail['input_sequence']),10)
        self.assertFalse(detail['input_truncated'])

    def test_long_task_notes_are_compact_and_full_notes_remain_readable(self):
        notes='Complete task requirements. '*350
        task=self.s.task(self.i,self.pid,self.staff['Lead Designer'],'A long task',notes)
        packet=self.c.work_packet(self.row,self.progress)
        self.assertEqual(packet['tasks'][0]['notes_chars'],len(notes))
        self.assertEqual(len(packet['tasks'][0]['notes']),300)
        result=self.action('task_read',task=task['id'])
        self.assertIn('result_id',result)
        self.assertEqual(json.loads(self.progress['result_detail']['text'])['notes'],notes)
        second=self.s.ingest(self.i,'Different task project',[('x.c',b'int x;')],dict(kind='fixture'))
        self.row['project']=second['project']
        with self.assertRaises(PermissionError):self.action('task_read',task=task['id'])

    def test_large_tool_result_journal_records_digest_without_repeating_full_payload(self):
        ref=self.s.start_workflow(self.i,self.pid,self.staff['Studio Lead'],'Journal fixture','Retain a compact pointer.')['id']
        with self.s.db() as cx,cx:cx.execute('UPDATE studio_workflows SET artifacts=? WHERE id=?',(encoded(dict(pending_handoff=dict(summary='x'*6000))),ref))
        result=self.action('workflow_read',workflow=ref,artifact='pending_handoff')
        with self.s.db() as cx:
            event=json.loads(cx.execute("SELECT body FROM studio_events WHERE job=? AND kind='workflow_read' ORDER BY rowid DESC LIMIT 1",(self.row['id'],)).fetchone()[0])
        self.assertEqual(event['result']['result_id'],sha(self.progress['result_detail']['text']))
        self.assertEqual(event['result'],result)
        self.assertLess(len(encoded(event).encode()),2000)

    def infer_fixture(self,packet,context=16384):
        self.f.engine.text_models={'local':dict(num_ctx=context)}
        settings=dict(actor=self.staff['Lead Designer'],turn_limit=10,token_budget=100000)
        jid=ident('studio-job')
        with self.s.db() as cx,cx:cx.execute('INSERT INTO studio_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(jid,self.i,self.pid,'work','running',encoded(settings),'{}',60,0,0,'Fixture',0))
        self.c.deadlines[jid]=time.monotonic()+60
        return self.c.infer(jid,'System instructions remain intact.',packet)

    def test_context_pressure_preserves_objective_actions_and_paged_tool_result(self):
        packet=dict(objective='Keep this objective.',instructions='Approved direction.',available_actions=dict(result_read='{result_id,start,chars}'),
            last_result=dict(result_id='stable',total_chars=9000,preview='preview'),members=['x'*15000],memory_map=dict(fast_access=['approved memory']))
        self.infer_fixture(packet)
        supplied=json.loads(self.f.engine.calls[-1]['messages'][-1]['content'])
        for key in ('objective','instructions','available_actions','last_result','memory_map'):self.assertEqual(supplied[key],packet[key])
        self.assertEqual(supplied['context_omitted']['fields'],['members'])
        self.assertIn('members',packet)

    def test_oversized_required_context_fails_before_model_call(self):
        packet=dict(objective='x'*16000,instructions='Must not truncate.',available_actions={})
        before=len(self.f.engine.calls)
        with self.assertRaisesRegex(ValueError,'configured model context'):self.infer_fixture(packet)
        self.assertEqual(len(self.f.engine.calls),before)


if __name__=='__main__':unittest.main()
