"""Real SQLite institution boundaries and deterministic local inference fixtures."""
import concurrent.futures
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import zipfile
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'payload')]
import village
import village_memory as memory
from studio_store import Store,unpack,files,sha
from studios import Studios


class Engine:
    def __init__(self,root):
        self.root=root/'control';self.root.mkdir();self.captain=dict(enabled=True,model_id='local');self.commons=self.founding=None;self.mode='max';self.calls=[];self.responses=[]
    def mode_status(self):return dict(mode=self.mode,transitioning=False,error=None)
    def submit(self,body,studio_turn=None):
        assert self.studios.owns(studio_turn);assert body['inference_only'] and not body.get('tools')
        self.calls.append(body);packet=json.loads(body['messages'][-1]['content']);f=concurrent.futures.Future()
        if self.responses:f.set_result(self.responses.pop(0))
        elif 'sources' in packet and 'objective' not in packet:
            source=packet['sources'][0];e=dict(source=source['source'],path=source['path'],digest=source['digest'],quote=source.get('text',source.get('quote',''))[:50])
            f.set_result(json.dumps(dict(items=[dict(title='Update loop',text='The reference increments a counter. Runtime behaviour remains unverified.',evidence=[e])])) )
        elif 'assignment' in packet:f.set_result(json.dumps(dict(report='The assignment is bounded and needs a cartridge check before acceptance.')))
        elif 'learning_id' in packet:f.set_result(json.dumps(dict(decision='accept',title='Evidence-backed lesson',lesson=packet['lesson'])))
        elif packet.get('last_result',{}).get('saved'):f.set_result(json.dumps(dict(action='done',args=dict(summary='No unverified claims.'),note='Keep this project note.')))
        else:f.set_result(json.dumps(dict(action='learning_none',args=dict(reason='No reusable learning in this fixture turn.'),note='Keep this project note.')))
        return f


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.engine=Engine(self.root);self.connector=lambda p:village.connect(p,test_encrypted=True)
        self.c=Studios(self.engine,self.connector);self.engine.studios=self.c;self.addCleanup(self.c.shutdown)
        self.s=self.c.store;self.i=self.s.create('Small studio','Learn from two C games')['id']
        self.p=self.s.ingest(self.i,'First game',[('game.c',b'int counter; void update(void) { counter++; }\n'),('notes.md',b'Private original notes: ALPHA_SECRET')],dict(kind='fixture'))
    def approve(self,ref):
        p=self.s.preview(ref);return self.s.review(ref,p['review_digest'],'approve')
    def wait(self,jid):
        deadline=time.monotonic()+5
        while self.c.active and time.monotonic()<deadline:time.sleep(.01)
        with self.s.db() as cx:return dict(cx.execute('SELECT * FROM studio_jobs WHERE id=?',(jid,)).fetchone())
    def test_intake_preserves_original_and_work_edits_do_not_change_it(self):
        original=self.s.directory/self.i.split(':')[1]/'archive'/(self.p['source'].split(':')[1]+'.zip')
        before=original.read_bytes();r=self.s.read(self.p['project'],'game.c')
        self.s.edit(self.p['project'],'game.c','int modified;',r['sha256'])
        self.assertEqual(original.read_bytes(),before)
        with self.assertRaises(ValueError):self.s.edit(self.p['project'],'game.c','bad',r['sha256'])
        with self.assertRaises(ValueError):self.s.read(self.p['project'],'../escape')
    def test_zip_traversal_and_case_collisions_are_rejected(self):
        for names in [['../evil'],['A.c','a.c']]:
            b=io.BytesIO()
            with zipfile.ZipFile(b,'w') as z:
                for n in names:z.writestr(n,'source')
            with self.assertRaises(ValueError):unpack(b.getvalue())
    def test_staff_approval_and_private_library_never_enter_general(self):
        staff=self.s.prepare_staff(self.i)
        with self.s.db() as cx:self.assertEqual(len(village.status(cx)),5)
        lead=self.approve(staff[0]['id'])['resident']
        with self.s.db() as cx:
            self.assertEqual(self.s.member(cx,self.i,lead),'Lead Designer')
            with self.assertRaises(PermissionError):self.s.member(cx,self.i,'coder.general')
        evidence=[dict(source=self.p['source'],path='game.c',digest=sha(b'int counter; void update(void) { counter++; }\n'),quote='counter++')]
        proposal=self.s.propose(self.i,'library',dict(title='Secret workflow',text='ALPHA_SECRET'),evidence)
        doc=self.approve(proposal['id'])['citation']
        with self.s.db() as cx:
            self.assertEqual(memory.document_search(cx,'coder.general','ALPHA',['general']),[])
            scope=self.s.institution(cx,self.i)['collection']
            self.assertIn('ALPHA',memory.document_read(cx,lead,doc,[scope])['text'])
        for r in self.s.view(self.i)['proposals']:
            if r['kind']=='map' and r['state']=='pending':
                try:self.approve(r['id'])
                except ValueError:pass
    def test_exact_quotes_and_source_withdrawal_invalidate_documents(self):
        e=dict(source=self.p['source'],path='game.c',digest=sha(b'int counter; void update(void) { counter++; }\n'),quote='fabricated')
        with self.assertRaises(PermissionError):self.s.propose(self.i,'library',dict(title='x',text='x'),[e])
        e['quote']='counter++';p=self.s.propose(self.i,'library',dict(title='Loop',text='Uses a counter'),[e]);doc=self.approve(p['id'])['citation']
        plan=self.s.withdraw(self.i,self.p['source'],'')
        self.s.withdraw(self.i,self.p['source'],plan['digest'],True)
        with self.s.db() as cx:self.assertEqual(cx.execute('SELECT state FROM library_documents WHERE id=?',(doc,)).fetchone()[0],'withdrawn')
        with self.assertRaises(PermissionError):self.s.read(self.p['project'],'game.c')
    def test_founding_prepares_citations_and_staff_but_never_approves(self):
        self.s.ingest(self.i,'Second game',[('second.c',b'int counter; void tick(void) { counter += 2; }')],dict(kind='fixture'))
        job=self.c.start(dict(institution=self.i,kind='founding',turns=10))['id'];row=self.wait(job)
        self.assertEqual(row['state'],'complete',row['reason'])
        proposals=self.s.view(self.i)['proposals'];self.assertTrue(any(p['kind']=='library' for p in proposals));self.assertEqual(sum(p['kind']=='staff' for p in proposals),6)
        with self.s.db() as cx:self.assertEqual(len(village.status(cx)),5)
        self.assertTrue(all(p['state']=='pending' for p in proposals))
    def test_project_ownership_notes_and_explicit_resume(self):
        lead=self.approve(self.s.prepare_staff(self.i)[0]['id'])['resident']
        job=self.c.start(dict(institution=self.i,kind='work',project=self.p['project'],resident=lead,objective='Inspect'))['id']
        row=self.wait(job);self.assertEqual(row['state'],'complete',row['reason'])
        self.assertIn('Keep this project note',json.loads(row['progress'])['notes'])
        calls=len(self.engine.calls);self.c.pause();time.sleep(.02);self.assertEqual(len(self.engine.calls),calls)
    def test_owner_review_requires_matching_preview(self):
        ref=self.s.prepare_staff(self.i)[0]['id']
        with self.assertRaises(ValueError):self.s.review(ref,'stale','approve')
        result=self.approve(ref);self.assertEqual(self.approve(ref),result)
        first=self.s.view(self.i);second=self.s.view(self.i,1)
        self.assertEqual(first['proposals'][1]['id'],second['proposals'][0]['id'])
        self.assertEqual(first['proposal_total'],second['proposal_total'])
    def test_upload_offsets_and_explicit_source_selection(self):
        upload=self.c.upload_begin()['upload'];self.c.upload(upload,0,b'abc')
        with self.assertRaises(ValueError):self.c.upload(upload,0,b'wrong')
        with self.assertRaises(ValueError):self.c.upload('../wrong',0,b'wrong')
    def test_cross_institution_access_is_denied(self):
        lead=self.approve(self.s.prepare_staff(self.i)[0]['id'])['resident'];other=self.s.create('Other','Separate')['id']
        with self.s.db() as cx:
            with self.assertRaises(PermissionError):self.s.member(cx,other,lead)
            with self.assertRaises(PermissionError):self.s.project(cx,self.p['project'],other)

    def test_resident_tools_follow_the_advertised_paths_and_memory_review(self):
        lead=self.approve(self.s.prepare_staff(self.i)[0]['id'])['resident']
        row=dict(id='fixture',institution=self.i,project=self.p['project'],settings=json.dumps(dict(actor=lead)))
        progress=dict(notes='')
        result,_=self.c.work_action(row,progress,dict(action='read',args=dict(path='game.c')))
        self.c.work_action(row,progress,dict(action='edit',args=dict(path='new.c',text='int new_value;',expected='')))
        self.assertIn('counter',result['text']);self.assertEqual(self.s.read(self.p['project'],'new.c')['text'],'int new_value;')
        p,_=self.c.work_action(row,progress,dict(action='propose',args=dict(kind='memory',title='Build lesson',text='Use the studio tests before reporting success.')))
        self.approve(p['id'])
        proposals=self.s.view(self.i)['proposals']
        maps=[p for p in proposals if p['kind']=='map' and p['payload']['spec']['fast_access']]
        self.assertTrue(maps);self.approve(maps[0]['id'])
        with self.s.db() as cx:self.assertTrue(memory.packet(cx,lead,[self.s.institution(cx,self.i)['collection'],'general'])['fast_access'])

    def staff(self):
        out={}
        for p in self.s.prepare_staff(self.i):
            proposal=self.s.preview(p['id'])
            result=self.s.review(p['id'],proposal['review_digest'],'approve')
            out[result['title']]=result['resident']
        return out

    def test_staff_proposals_add_studio_lead_and_lead_developer(self):
        proposals=self.s.prepare_staff(self.i)
        titles={p['payload']['title'] for p in self.s.view(self.i)['proposals'] if p['kind']=='staff'}
        self.assertEqual(len(proposals),6)
        self.assertIn('Studio Lead',titles);self.assertIn('Lead Developer',titles)
        self.assertTrue(all(p['state']=='pending' for p in self.s.view(self.i)['proposals'] if p['kind']=='staff'))

    def test_delegated_assignments_follow_role_hierarchy_and_are_saved(self):
        staff=self.staff();lead=staff['Studio Lead'];developer=staff['Lead Developer'];designer=staff['Lead Designer'];engine=staff['Engine specialist']
        with self.assertRaises(PermissionError):self.s.delegate(self.i,self.p['project'],designer,engine,'Unscoped request')
        with self.assertRaises(PermissionError):self.s.delegate(self.i,self.p['project'],lead,designer,'Skip layer')
        assignment=self.s.delegate(self.i,self.p['project'],lead,developer,'Review implementation plan','Focus on portability.')
        with self.s.db() as cx:
            saved=dict(cx.execute('SELECT * FROM studio_delegations WHERE id=?',(assignment['id'],)).fetchone())
            task=dict(cx.execute('SELECT * FROM studio_tasks WHERE id=?',(assignment['task'],)).fetchone())
        self.assertEqual(saved['assignee'],developer);self.assertEqual(task['owner'],developer)

    def test_lead_developer_assignment_runs_one_analysis_turn_not_an_independent_worker(self):
        staff=self.staff();lead=staff['Studio Lead'];developer=staff['Lead Developer']
        self.engine.responses=[json.dumps(dict(action='delegate',args=dict(resident=developer,title='Review the proposed update loop',notes='Check whether the design claim is supported.'),note='Assign focused analysis.'))]
        job=self.c.start(dict(institution=self.i,kind='work',project=self.p['project'],resident=lead,objective='Coordinate one technical question.',turns=8))['id']
        row=self.wait(job);self.assertEqual(row['state'],'complete',row['reason'])
        with self.s.db() as cx:
            assignment=dict(cx.execute('SELECT * FROM studio_delegations').fetchone())
            task=dict(cx.execute('SELECT * FROM studio_tasks WHERE id=?',(assignment['task'],)).fetchone())
        delegate_event=next(e for e in self.s.view(self.i)['events'] if e['kind']=='delegate')
        delegate_result=delegate_event['body']['result']
        self.assertEqual(assignment['state'],'complete',assignment);self.assertIn('bounded',assignment['result'])
        self.assertEqual(task['state'],'done');self.assertEqual(len([c for c in self.engine.calls if json.loads(c['messages'][-1]['content']).get('assignment')]),1)
        self.assertFalse(delegate_result['independent_worker']);self.assertFalse(delegate_result['can_edit']);self.assertFalse(delegate_result['can_run_tests'])

    def test_temporary_appointment_is_owner_approved_and_exactly_scoped(self):
        staff=self.staff();lead=staff['Studio Lead'];developer=staff['Lead Developer'];recruit='coder.general'
        task=self.s.task(self.i,self.p['project'],developer,'Inspect one assigned file','Check the source and run the cartridge tests.')
        proposal=self.s.propose_appointment(self.i,self.p['project'],task['id'],recruit,'coder','Temporary test specialist',2,developer)
        with self.s.db() as cx:
            self.assertEqual(cx.execute('SELECT count(*) FROM studio_appointments').fetchone()[0],0)
            with self.assertRaises(PermissionError):self.s.member(cx,self.i,recruit)
        preview=self.s.preview(proposal['id']);result=self.s.review(proposal['id'],preview['review_digest'],'approve')
        appointment=result['appointment']
        self.assertFalse(result['permanent_membership'])
        row=dict(id='temporary-work',kind='work',institution=self.i,project=self.p['project'],settings=json.dumps(dict(actor=recruit,appointment=appointment,objective='Inspect the assigned work order.')))
        progress=dict(notes='',last_result={})
        self.s.read(self.p['project'],'game.c')
        self.c.work_action(row,progress,dict(action='edit',args=dict(path='temporary.c',text='int temporary_work;',expected='')))
        self.c.workbench.tests=lambda iid,build:dict(ok=True,tests=1)
        tests,_=self.c.work_action(row,progress,dict(action='tests',args=dict(build='fixture-build')))
        self.assertTrue(tests['ok'])
        with self.assertRaises(PermissionError):self.c.work_action(row,progress,dict(action='help',args=dict(resident=lead,question='Can I see your memories?')))
        packet=self.c.work_packet(row,dict(notes='',last_result={}))
        self.assertEqual(packet['members'],[]);self.assertEqual(packet['sources'],[]);self.assertEqual(packet['approved_documents'],[]);self.assertEqual(packet['memory_map'],{})
        started=self.c.start(dict(institution=self.i,kind='work',project=self.p['project'],appointment=appointment,turns=5))
        completed=self.wait(started['id']);self.assertEqual(completed['state'],'complete',completed['reason'])
        with self.s.db() as cx:
            self.assertEqual(cx.execute('SELECT state FROM studio_appointments WHERE id=?',(appointment,)).fetchone()[0],'completed')
            self.assertEqual(cx.execute('SELECT state FROM studio_tasks WHERE id=?',(task['id'],)).fetchone()[0],'done')
        with self.s.db() as cx:self.assertEqual(cx.execute('SELECT work_order FROM studio_appointments WHERE id=?',(appointment,)).fetchone()[0],task['id'])
        self.assertEqual(self.s.revoke_appointment(self.i,appointment)['state'],'completed')
        with self.assertRaises(PermissionError):self.c.work_action(row,progress,dict(action='read',args=dict(path='game.c')))

    def test_work_closeout_requires_learning_or_explicit_none(self):
        lead=self.staff()['Lead Designer']
        row=dict(id='closeout-job',kind='work',institution=self.i,project=self.p['project'],settings=json.dumps(dict(actor=lead)))
        progress=dict(notes='',last_result={})
        with self.assertRaises(ValueError):self.c.work_action(row,progress,dict(action='done',args=dict(summary='Finished')))
        self.c.work_action(row,progress,dict(action='learning_none',args=dict(reason='No reusable lesson was supported by this turn.')))
        result,done=self.c.work_action(row,progress,dict(action='done',args=dict(summary='Finished')))
        self.assertTrue(done);self.assertEqual(result['summary'],'Finished')

    def test_studio_lead_curation_archives_accepted_learning_for_later_work(self):
        staff=self.staff();author=staff['Lead Designer'];curator=staff['Studio Lead']
        lesson=self.s.learn(self.i,self.p['project'],'studio-task:fixture',author,'institution','Keep rendering pure; update simulation state before drawing.','The authored cartridge test observed stable metrics across repeated vm_draw calls.')
        with self.assertRaises(PermissionError):self.s.curate_learning(self.i,self.p['project'],author,lesson['id'],'accept','Own work','No review.')
        job=self.c.start(dict(institution=self.i,kind='curation',project=self.p['project'],resident=curator,turns=5))['id']
        result=self.wait(job);self.assertEqual(result['state'],'complete',result['reason'])
        with self.s.db() as cx:
            curated=cx.execute('SELECT state,curator FROM studio_learnings WHERE id=?',(lesson['id'],)).fetchone()
            artifact=cx.execute("SELECT body FROM studio_artifacts WHERE kind='learning'").fetchone()
        self.assertEqual(curated['state'],'accepted');self.assertEqual(curated['curator'],curator)
        self.assertIn('Evidence from studio-task:fixture',artifact['body'])
        row=dict(id='next-work',kind='work',institution=self.i,project=self.p['project'],settings=json.dumps(dict(actor=author,objective='Use accepted studio learning.')))
        packet=self.c.work_packet(row,dict(notes='',last_result={}))
        self.assertEqual(packet['accepted_learning'][0]['id'],lesson['id'])
        self.assertIn('RETROSPECTIVE:',result['progress'])


if __name__=='__main__':unittest.main()
