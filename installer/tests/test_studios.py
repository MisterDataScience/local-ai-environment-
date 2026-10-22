"""Real SQLite institution boundaries and deterministic local inference fixtures."""
import concurrent.futures
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'payload')]
import village
import village_memory as memory
from studio_store import Store,unpack,files,archive,sha
from studios import Studios


class Engine:
    def __init__(self,root):
        self.root=root/'control';self.root.mkdir();self.captain=dict(enabled=True,model_id='local');self.commons=self.founding=None;self.mode='max';self.calls=[]
    def mode_status(self):return dict(mode=self.mode,transitioning=False,error=None)
    def submit(self,body,studio_turn=None):
        assert self.studios.owns(studio_turn);assert body['inference_only'] and not body.get('tools')
        self.calls.append(body);packet=json.loads(body['messages'][-1]['content']);f=concurrent.futures.Future()
        system=body['messages'][0]['content']
        if system.startswith('You are the Studio Lead.'):
            f.set_result(json.dumps(dict(decision='accept',review='Handoff is complete and stage evidence is present.',next_focus='')))
        elif 'sources' in packet and 'objective' not in packet:
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
        proposals=self.s.view(self.i)['proposals'];self.assertTrue(any(p['kind']=='library' for p in proposals));self.assertEqual(sum(p['kind']=='staff' for p in proposals),5)
        with self.s.db() as cx:self.assertEqual(len(village.status(cx)),5)
        self.assertTrue(all(p['state']=='pending' for p in proposals))
    def test_studio_lead_runs_sequential_department_handoffs(self):
        staff=self.s.prepare_staff(self.i)
        approved={self.approve(item['id'])['title']:True for item in staff}
        self.assertIn('Studio Lead',approved)
        # The fake inference engine returns done at every stage. Bypass only the
        # playtest evidence contract here; the gate itself has separate tests.
        with patch.object(self.c,'production_gate_missing',return_value=[]):
            job=self.c.start(dict(institution=self.i,kind='production',project=self.p['project'],objective='Make a small game'))['id']
            row=self.wait(job)
        self.assertEqual(row['state'],'complete',row['reason'])
        progress=json.loads(row['progress'])
        self.assertEqual(progress['pipeline_stage'],'complete')
        self.assertEqual(progress['completed_stages'],['planning','middle','implementation','playtest'])
        self.assertIn('Keep this project note',progress['notes'])
        with self.s.db() as cx:
            production=cx.execute('SELECT state,stage,handoffs FROM studio_productions WHERE job=?',(job,)).fetchone()
        self.assertEqual((production['state'],production['stage']),('complete','complete'))
        self.assertEqual(set(json.loads(production['handoffs'])),{'planning','middle','implementation','playtest'})

    def test_playtest_gate_requires_build_tests_run_and_visual_review(self):
        progress=dict(acceptance=dict(build=None,tests=None,run=None,visual=None))
        missing=self.c.production_gate_missing(self.p['project'],progress)
        self.assertEqual(len(missing),4)
        self.assertTrue(any('build' in item for item in missing))
        self.assertTrue(any('tests' in item for item in missing))
        self.assertTrue(any('machine run' in item for item in missing))
        self.assertTrue(any('visual inspection' in item for item in missing))

    def test_playtest_gate_rejects_stale_build_after_working_copy_edit(self):
        source=sha(archive(files(self.s.path(self.p['project']))))
        acceptance=dict(
            build=dict(id='build:fixture',state='passed',source_sha256=source),
            tests=dict(build='build:fixture',passed=True),
            run=dict(build='build:fixture',evidence='evidence:fixture',screen_sha256='screen-hash',steps=10),
            visual=dict(build='build:fixture',evidence='evidence:fixture',screen_sha256='screen-hash',image_sent=True,status='pass'))
        progress=dict(acceptance=acceptance)
        self.assertEqual(self.c.production_gate_missing(self.p['project'],progress),[])
        self.s.edit(self.p['project'],'game.c','int counter; void update(void) { counter += 2; }\n',sha(b'int counter; void update(void) { counter++; }\n'))
        self.assertTrue(any('current working-copy revision' in item for item in self.c.production_gate_missing(self.p['project'],progress)))

    def test_visual_revision_routes_production_back_to_implementation(self):
        machine='machine:visual-review'
        self.c.workbench.machines[machine]=dict(institution=self.i,project=self.p['project'],build='build:fixture')
        progress=dict(pipeline_stage='playtest',stage_index=3,pipeline_phase='department',acceptance={})
        row=dict(kind='production',institution=self.i,project=self.p['project'])
        self.c.record_production_acceptance(row,progress,'inspect',dict(machine=machine),dict(
            evidence='evidence:visual-review',screen_sha256='screen-hash',
            visual_review=dict(status='revise',review='The player is not visible.',issues=['No player sprite is rendered.'])))
        self.assertEqual((progress['pipeline_stage'],progress['stage_index']),('implementation',2))
        self.assertIn('No player sprite is rendered.',progress['stage_feedback'])
        self.assertIsNone(progress['acceptance']['build'])

    def test_headless_inspect_sends_rendered_png_to_configured_model(self):
        lead=self.approve(self.s.prepare_staff(self.i)[0]['id'])['resident']
        machine='machine:headless-inspect'
        self.c.workbench.machines[machine]=dict(institution=self.i,project=self.p['project'],build='build:fixture')
        png=(b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\x0dIHDR'+(320).to_bytes(4,'big')+(180).to_bytes(4,'big')+b'\x08\x06\x00\x00\x00')
        png64=base64.b64encode(png).decode()
        self.c.workbench.machine=lambda *args,**kwargs:dict(png=png64,screen_sha256='frame-hash',metrics={},evidence='evidence:frame')
        seen={}
        def infer(jid,system,packet,image=None):
            seen['image']=image
            return json.dumps(dict(status='pass',review='Player and obstacle are visible.',issues=[]))
        self.c.infer=infer
        self.c.store.event=lambda *args,**kwargs:None
        row=dict(id='fixture-job',institution=self.i,project=self.p['project'],kind='production',settings=json.dumps(dict(actor=lead)))
        progress=dict(acceptance=dict(build=dict(id='build:fixture',state='passed',source_sha256='unused')))
        result,_=self.c.work_action(row,progress,dict(action='inspect',args=dict(machine=machine,question='Is the player visible?')))
        self.assertEqual(seen['image'],png64)
        self.assertTrue(result['image_sent'])
        self.assertEqual(progress['acceptance']['visual']['screen_sha256'],'frame-hash')

    def test_only_one_active_production_per_studio(self):
        for item in self.s.prepare_staff(self.i):self.approve(item['id'])
        with self.s.db() as cx,cx:
            self.s.begin_production(cx,self.i,self.p['project'],'studio-job-reserved')
        other=self.s.ingest(self.i,'Second game',[('other.c',b'int other;')],dict(kind='fixture'))
        with self.assertRaisesRegex(RuntimeError,'already has an active production'):
            self.c.start(dict(institution=self.i,kind='production',project=other['project'],objective='Another game'))
        cancelled=self.c.cancel_production(self.i,self.p['project'])
        self.assertEqual(cancelled['state'],'cancelled')
        started=self.c.start(dict(institution=self.i,kind='production',project=other['project'],objective='Now the next game'))
        self.assertEqual(started['state'],'running')
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
        row=dict(id='fixture',institution=self.i,project=self.p['project'],kind='production',settings=json.dumps(dict(actor=lead)))
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


if __name__=='__main__':unittest.main()

