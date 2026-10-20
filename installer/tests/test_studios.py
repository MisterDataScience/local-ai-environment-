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
import game_scaffold
from studio_store import Store,unpack,files,sha
from studios import Studios


class Engine:
    def __init__(self,root):
        self.root=root/'control';self.root.mkdir();self.captain=dict(enabled=True,model_id='local');self.commons=self.founding=None;self.mode='max';self.calls=[]
    def mode_status(self):return dict(mode=self.mode,transitioning=False,error=None)
    def submit(self,body,studio_turn=None):
        assert self.studios.owns(studio_turn);assert body['inference_only'] and not body.get('tools')
        self.calls.append(body);packet=json.loads(body['messages'][-1]['content']);f=concurrent.futures.Future()
        if 'sources' in packet and 'objective' not in packet:
            source=packet['sources'][0];e=dict(source=source['source'],path=source['path'],digest=source['digest'],quote=source.get('text',source.get('quote',''))[:50])
            f.set_result(json.dumps(dict(items=[dict(title='Update loop',text='The reference increments a counter. Runtime behaviour remains unverified.',evidence=[e])])) )
        else:f.set_result(json.dumps(dict(action='done',args=dict(summary='No unverified claims.'),note='Keep this project note.')))
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
        proposals=self.s.view(self.i)['proposals'];self.assertTrue(any(p['kind']=='library' for p in proposals));self.assertEqual(sum(p['kind']=='staff' for p in proposals),4)
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

    def test_design_department_stops_adaptively_with_audited_designer_deliverables(self):
        context={'institution':'Original Studio','mission':'Create original small games from approved C references. '*20,
            'approved_lessons':[dict(id='doc:'+str(i),title='Lesson '+str(i),text='A bounded approved lesson. '*24) for i in range(6)],
            'reference_projects':[dict(id='source:'+str(i),title='Reference '+str(i),paths=['src/'+('example'*12)+str(j)+'.c' for j in range(6)]) for i in range(8)],
            'source_evidence':[dict(source='source:'+str(i),path='src/'+str(i)+'.c',digest='a'*64,excerpt='int update(void) { state++; } '*15) for i in range(4)],
            'constraints':['No network or external models.','No implementation in planning.','Preserve owner approval boundaries.']}
        progress={'design':game_scaffold.initial_state(context), 'notes':'','elapsed':0}
        seen=[]
        def infer(jid,system,packet,image=None):
            packet_limit=8192-2560-len(system.encode())-100
            self.assertLessEqual(len(json.dumps(packet,ensure_ascii=False).encode()),packet_limit)
            if system.startswith('You are the Design Auditor'):
                return json.dumps({'verdict':'accept','checks':{'contract_met':True,'specific':True,'traceable':True,'complete_for_stage':True,'checkable':True},'findings':[],'reason':'Specific, complete for this branch and checkable.'})
            if packet.get('candidate_id'):
                i=int(packet['candidate_id'][1:]);seen.append(packet['department'])
                return json.dumps({'id':packet['candidate_id'],'title':'Candidate '+str(i),'player_experience':'The player changes a small living system through careful observation.','repeated_activity':'Observe a response, choose an intervention, and inspect what changed.','meaningful_choice':'Choose which resource to alter and accept its consequence.','distinctive_hook':'The world keeps traces of earlier choices.','demo_shape':'One short room with a complete start, decision, consequence and ending.','uncertainty':'Will players understand the consequence without explanation?'})
            if 'Choose one candidate' in system:
                return json.dumps({'selected_id':'C1','title':'Living Margins','root_answer':'Make a compact game about altering a living place through observation and consequential choices.','contract':{'player_goal':'Change the place enough to reach a clear ending.','repeated_play':'Observe, choose an intervention, inspect the consequence.','intended_appeal':'Feel clever for understanding a small ecology.','demo_boundary':'One self-contained playable place.','completion_rule':'Reach a changed but stable end state.','exclusions':'No campaign or large inventory.'},'first_questions':['What does the player observe and choose?','Which world rules react to a choice?','How is the place organized over time?','How are consequences taught and shown?','What makes the short demo complete?'],'rejected':[]})
            if packet.get('stage')=='whole dossier integration review':
                self.assertEqual(len(packet['branch_summaries']),5)
                return json.dumps({'verdict':'accept','checks':{'contract_met':True,'specific':True,'traceable':True,'complete_for_stage':True,'checkable':True},'findings':[],'reason':'All top-level branches trace to the game promise.'})
            if packet.get('node'):
                return json.dumps({'answer':'This decision is resolved as one bounded specification, and no consequential design question remains open at this level.','disposition':'leaf','children':[],'leaf':{'deliverable':'A one-page rule specification for this part of the game.','instruction':'Write the exact rule, its inputs, resulting state changes and edge cases.','inputs':['selected game contract','parent design answer'],'outputs':['rule specification'],'depends_on':[],'sufficiency_check':'The specification states each input, state change, edge case and expected result required by the parent decision.','evidence':['rule specification','worked example']}})
            return json.dumps({'answer':'This branch resolves one design decision precisely enough for the Lead Designer to complete its stated deliverable.','disposition':'leaf','children':[],'leaf':{'deliverable':'A one-page rule specification for this part of the game.','instruction':'Write the exact rule, its inputs, resulting state changes and edge cases.','inputs':['selected game contract','parent design answer'],'outputs':['rule specification'],'depends_on':[],'sufficiency_check':'The specification states each input, state change, edge case and expected result required by the parent decision.','evidence':['rule specification','worked example']}})
        self.c.infer=infer
        row={'id':'fixture-design','institution':self.i,'kind':'design'}
        done=False
        for _ in range(40):
            progress,done=self.c.design_step(row,progress)
            progress=json.loads(json.dumps(progress))  # durable JSON checkpoint between turns
            if done:break
        self.assertTrue(done)
        self.assertEqual(len(progress['design']['candidates']),4)
        self.assertEqual(len(set(seen)),4)
        state=progress['design']
        self.assertEqual(state['nodes'][0]['id'],'G0')
        self.assertTrue(state['nodes'][0]['audited'])
        self.assertEqual(state['leaf_count'],5)
        self.assertTrue(all(n['depth']==1 for n in state['nodes'] if n['state']=='leaf'))
        self.assertLess(state['leaf_count'],1000)


if __name__=='__main__':unittest.main()
