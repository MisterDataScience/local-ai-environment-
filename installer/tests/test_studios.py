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
from studio_roles import ACTION_SPECS,ROLE_ACTIONS,CORE_STAFF_ROLES,MAX_SPECIALIST_SUBTASKS


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
        elif 'assignment' in packet:
            if packet.get('last_result',{}).get('saved'):f.set_result(json.dumps(dict(action='done',args=dict(summary='Independent worker completed with bounded evidence.'),note='Return the saved work order.')))
            else:f.set_result(json.dumps(dict(action='learning_none',args=dict(reason='No additional reusable learning.'),note='Close the independent assignment.')))
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
    def test_role_action_profiles_are_canonical_and_playtest_is_report_only(self):
        self.assertTrue(all(action in ACTION_SPECS for profile in ROLE_ACTIONS.values() if isinstance(profile,(set,frozenset)) for action in profile))
        self.assertNotIn('finding',ROLE_ACTIONS['test'])
        self.assertIn('workflow_verify',ROLE_ACTIONS['test'])
        self.assertIn('workflow_return',ROLE_ACTIONS['manager'])
        self.assertEqual(MAX_SPECIALIST_SUBTASKS,3)
        self.assertEqual(len(CORE_STAFF_ROLES),5)

    def test_staged_workflow_enforces_department_order_and_records_provenance(self):
        residents={}
        for proposal in self.s.prepare_staff(self.i):
            approved=self.approve(proposal['id'])
            residents[approved['title']]=approved['resident']
        lead=residents['Studio Lead'];designer=residents['Lead Designer'];test_planner=residents['Systems designer']
        developer=residents['Lead Developer'];reviewer=residents['Playtest reviewer']
        engine=residents['Systems designer']
        workflow=self.s.start_workflow(self.i,self.p['project'],lead,'Adapt counter game','Extract one small portable-C experiment')
        ref=workflow['id'];project=self.p['project']
        with self.assertRaises(PermissionError):
            self.s.delegate(self.i,project,lead,developer,'Skip stages','',mode='delivery')
        plan=self.s.delegate(self.i,project,lead,designer,'Reverse scaffold','Map source architecture',mode='design',workflow=ref,phase='planning')
        evidence=[dict(source=self.p['source'],path='game.c',digest=sha(b'int counter; void update(void) { counter++; }\n'),quote='counter++')]
        step=self.s.save_workflow_step(self.i,ref,project,designer,'Main loop','Observed update increments counter.',evidence)
        self.assertEqual(step['phase'],'planning')
        self.s.finish_delegation(plan['id'],'complete','Reverse scaffold recorded.')
        workflow_view=self.s.workflow_view(self.i,ref)
        self.assertEqual(workflow_view['phase'],'middle')
        self.assertEqual(workflow_view['phase_label'],'Design Integration and Production Planning')
        with self.assertRaises(PermissionError):
            self.s.delegate(self.i,project,lead,developer,'Skip test plan','',mode='delivery',workflow=ref,phase='implementation')
        test_plan_assignment=self.s.delegate(self.i,project,lead,test_planner,'Test plan','Define deterministic assertions.',mode='test-plan',workflow=ref,phase='middle')
        self.s.save_workflow_step(self.i,ref,project,test_planner,'Counter assertion','After one update, counter increases by one.',evidence)
        self.s.finish_delegation(test_plan_assignment['id'],'complete','Test plan saved.')
        self.assertEqual(self.s.workflow_view(self.i,ref)['phase'],'implementation')
        build=self.s.delegate(self.i,project,lead,developer,'Implement experiment','',mode='delivery',workflow=ref,phase='implementation')
        with self.assertRaises(PermissionError):
            self.s.delegate(self.i,project,developer,engine,'Unlinked implementation task','',mode='implementation')
        worker_row=dict(id='lead-developer-work',kind='assignment',institution=self.i,project=project,settings=json.dumps(dict(actor=developer,actor_title='Lead Developer',objective='Implement the agreed experiment.',assignment_id=build['id'],assignment_mode='lead-developer',workflow=ref,workflow_phase='implementation')))
        original_start=self.c.start;started=[]
        self.c.start=lambda request:(started.append(request) or dict(id='queued-child-job'))
        try:
            child_result,_=self.c.work_action(worker_row,dict(notes='',last_result={}),dict(action='delegate',args=dict(resident=engine,title='Implement one bounded update-loop change',notes='Follow the Design Integration and Production Planning checkpoints.',mode='implementation')))
        finally:self.c.start=original_start
        child=self.s.team_status(self.i,project,developer,build['id'])['children'][0]
        self.assertEqual(child['id'],child_result['id']);self.assertEqual(child['mode'],'implementation')
        self.assertEqual(child['workflow'],ref);self.assertEqual(child['phase'],'implementation');self.assertEqual(child_result['parent'],build['id'])
        self.assertEqual(started[0]['assignment_id'],child_result['id'])
        child_row=dict(id='implementation-child-job',kind='assignment',institution=self.i,project=project,settings=json.dumps(dict(actor=engine,actor_title='Systems designer',objective='Implement the bounded change.',assignment_id=child_result['id'],assignment_mode='implementation',workflow=ref,workflow_phase='implementation')))
        child_packet=self.c.work_packet(child_row,dict(notes='',last_result={}))
        self.assertTrue(any(step['title']=='Counter assertion' for step in child_packet['workflow']['steps']))
        self.assertEqual(child_packet['assignment']['parent'],build['id'])
        with self.assertRaises(RuntimeError):
            self.s.delegate(self.i,project,developer,test_planner,'Check an uncertain acceptance criterion','Return a focused analysis.',mode='analysis',workflow=ref,phase='implementation',parent=build['id'])
        with self.assertRaises(PermissionError):
            self.c.work_action(worker_row,dict(notes='',last_result={}),dict(action='edit',args={}))
        with self.assertRaises(ValueError):self.s.finish_delegation(build['id'],'complete','Implementation report.')
        self.assertEqual(self.s.workflow_view(self.i,ref)['phase'],'implementation')
        self.s.finish_delegation(child_result['id'],'complete','Implemented the bounded update-loop change.')
        team=self.s.team_status(self.i,project,developer,build['id'])
        self.assertEqual((team['total'],team['active']),(1,0))
        blocked_child=self.s.delegate(self.i,project,developer ,test_planner,'Check an uncertain acceptance criterion','Return a focused analysis and identify what remains unknown.',mode='analysis',workflow=ref,phase='implementation',parent=build['id'])
        team=self.s.team_status(self.i,project,developer,build['id'])
        self.assertEqual((team['total'],team['active']),(2,1))
        self.s.finish_delegation(blocked_child['id'],'blocked','The original source does not establish the expected screen result.')
        team=self.s.team_status(self.i,project,developer,build['id'])
        self.assertEqual((team['total'],team['active']),(2,0))
        self.s.finish_delegation(build['id'],'complete','Implementation report.')
        self.assertEqual(self.s.workflow_view(self.i,ref)['phase'],'verification')
        implementation=self.s.workflow_view(self.i,ref)['artifacts']['implementation'][0]
        child_states={child['state'] for child in implementation['children']}
        self.assertEqual(child_states,{'complete','blocked'})
        self.assertTrue(any('bounded update-loop change' in child['result'] for child in implementation['children']))
        test=self.s.delegate(self.i,project,lead,reviewer,'Verify experiment','',mode='test',workflow=ref,phase='verification')
        review_row=dict(id='playtest-job',kind='assignment',institution=self.i,project=project,settings=json.dumps(dict(actor=reviewer,actor_title='Playtest reviewer',objective='Verify the staged build.',assignment_id=test['id'],assignment_mode='test',workflow=ref,workflow_phase='verification')))
        review_packet=self.c.work_packet(review_row,dict(notes='',last_result={}))
        self.assertIn('workflow_verify',review_packet['available_actions'])
        self.assertIn('workflow_read',review_packet['available_actions'])
        self.assertNotIn('finding',review_packet['available_actions'])
        with self.assertRaises(PermissionError):
            self.c.work_action(review_row,dict(notes='',last_result={}),dict(action='finding',args=dict(category='Observed',text='Duplicate path.',evidence=['evidence:00000000000000000000000000000000'])))
        verification=dict(workflow=ref,verdict='verified',build=dict(build_id='build-001',source_digest='a'*64,build_status='success',runtime_status='loaded',errors=[],resources={'peak_memory_bytes':1024}),implementation_claims=[dict(claim='Update increments the counter.',status='reproduced',result='Replayed the update and observed one increment.',evidence=['build-001'])],tests=[dict(test_id='counter-once',description='One update increments counter once.',seed=1,inputs=['A'],expected='counter is 1',actual='counter is 1',status='passed',evidence=['build-001'])],findings=[],unverified_questions=[],explanation='The build loaded and the supplied deterministic assertion passed.')
        with self.assertRaises(ValueError):
            self.s.save_workflow_verification(self.i,ref,test['id'],reviewer,verification|dict(tests=[verification['tests'][0]|dict(status='failed')]))
        saved=self.s.save_workflow_verification(self.i,ref,test['id'],reviewer,verification)
        page,_=self.c.work_action(review_row,dict(notes='',last_result={}),dict(action='workflow_read',args=dict(workflow=ref,report_id=saved['id'],section='tests',offset=0,limit=2)))
        self.assertEqual(page['items'][0]['input_count'],1)
        self.assertNotIn('inputs',page['items'][0])
        self.s.finish_delegation(test['id'],'complete','Independent checks passed.')
        workflow_view=self.s.workflow_view(self.i,ref)
        self.assertEqual(workflow_view['state'],'ready_to_close')
        self.assertEqual(workflow_view['artifacts']['verification_reports'][0]['id'],saved['id'])
        self.assertEqual(workflow_view['artifacts']['verification_reports'][0]['tests'][0]['status'],'passed')
        self.s.close_workflow(self.i,ref,lead,'Verified and ready.')
        self.assertEqual(self.s.workflow_view(self.i,ref)['state'],'complete')
        self.assertTrue(self.s.recovery_check(self.i,project)['ok'])

    def test_blocked_implementation_waits_for_child_and_preserves_its_report_for_retry(self):
        residents=self.staff();lead=residents['Studio Lead'];designer=residents['Lead Designer'];test_planner=residents['Systems designer']
        developer=residents['Lead Developer'];engine=residents['Systems designer']
        project=self.p['project'];workflow=self.s.start_workflow(self.i,project,lead,'Adapt counter game','Implement one bounded experiment')['id']
        planning=self.s.delegate(self.i,project,lead,designer,'Planning','Build the reverse scaffold.',mode='design',workflow=workflow,phase='planning')
        self.s.finish_delegation(planning['id'],'complete','Scaffold saved.')
        test_plan=self.s.delegate(self.i,project,lead,test_planner,'Design Integration and Production Planning test plan','Define observable acceptance checks.',mode='test-plan',workflow=workflow,phase='middle')
        self.s.finish_delegation(test_plan['id'],'complete','Test plan saved.')
        implementation=self.s.delegate(self.i,project,lead,developer,'Implementation','Implement the agreed experiment.',mode='delivery',workflow=workflow,phase='implementation')
        child=self.s.delegate(self.i,project,developer,engine,'Bounded implementation task','Implement the counter update.',mode='implementation',workflow=workflow,phase='implementation',parent=implementation['id'])
        self.s.finish_delegation(implementation['id'],'blocked','Lead Developer session ended before the child report arrived.')
        self.assertEqual(self.s.workflow_view(self.i,workflow)['state'],'blocked')
        with self.assertRaises(RuntimeError):self.s.retry_workflow(self.i,workflow,lead,'Retry implementation before the child finishes.')
        self.assertEqual(self.s.team_status(self.i,project,developer,implementation['id'])['active'],1)
        self.s.finish_delegation(child['id'],'complete','Counter update implemented and checked.')
        report=self.s.workflow_view(self.i,workflow)['artifacts']['implementation'][0]['children'][0]
        self.assertEqual(report['state'],'complete');self.assertIn('implemented and checked',report['result'])
        self.s.retry_workflow(self.i,workflow,lead,'Resume after the child report arrived.')
        self.assertEqual(self.s.workflow_view(self.i,workflow)['state'],'active')

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
    def test_project_ownership_notes_and_explicit_resume(self):
        lead=self.approve(self.s.prepare_staff(self.i)[0]['id'])['resident']
        job=self.c.start(dict(institution=self.i,kind='work',project=self.p['project'],resident=lead,objective='Inspect'))['id']
        row=self.wait(job);self.assertEqual(row['state'],'complete',row['reason'])
        self.assertIn('Keep this project note',json.loads(row['progress'])['notes'])
        calls=len(self.engine.calls);self.c.pause();time.sleep(.02);self.assertEqual(len(self.engine.calls),calls)
    def test_studio_lead_override_links_the_verified_playtest_report(self):
        staff=self.staff();lead=staff['Studio Lead'];reviewer=staff['Playtest reviewer']
        ref=self.s.start_workflow(self.i,self.p['project'],lead,'Verified route override','Verify one deterministic result')['id']
        with self.s.db() as cx,cx:cx.execute("UPDATE studio_workflows SET phase='verification',state='active' WHERE id=?",(ref,))
        assignment=self.s.delegate(self.i,self.p['project'],lead,reviewer,'Verify','',mode='test',workflow=ref,phase='verification')
        report=self.s.save_workflow_verification(self.i,ref,assignment['id'],reviewer,dict(
            verdict='verified',
            build=dict(build_id='build-override',source_digest='c'*64,build_status='success',runtime_status='loaded',errors=[],resources={}),
            tests=[dict(test_id='loads',description='Cartridge loads.',seed=1,inputs=[],expected='loaded',actual='loaded',status='passed',evidence=['build-override'])],
            findings=[],unverified_questions=[],explanation='The build loaded and the only supplied test passed.'))
        self.s.finish_delegation(assignment['id'],'complete','Verification saved.')
        self.s.return_workflow(self.i,ref,lead,'A later integration check requires one more implementation pass.')
        view=self.s.workflow_view(self.i,ref)
        self.assertEqual((view['phase'],view['state']),('implementation','active'))
        self.assertEqual(view['history'][-1]['review_id'],report['id'])

    def test_playtest_return_to_middle_requires_checkpoints_linked_to_report(self):
        residents={}
        for proposal in self.s.prepare_staff(self.i):
            approved=self.approve(proposal['id'])
            residents[approved['title']]=approved['resident']
        lead=residents['Studio Lead'];reviewer=residents['Playtest reviewer'];planner=residents['Systems designer']
        workflow=self.s.start_workflow(self.i,self.p['project'],lead,'Review a source assumption','Verify the adaptation checkpoints')
        ref=workflow['id']
        with self.s.db() as cx,cx:cx.execute("UPDATE studio_workflows SET phase='verification',state='active' WHERE id=?",(ref,))
        assignment=self.s.delegate(self.i,self.p['project'],lead,reviewer,'Verify the experiment','',mode='test',workflow=ref,phase='verification')
        report=self.s.save_workflow_verification(self.i,ref,assignment['id'],reviewer,dict(verdict='return_to_middle',build=dict(build_id='build-002',source_digest='b'*64,build_status='success',runtime_status='loaded',errors=[],resources={}),tests=[dict(test_id='screen-state',description='Check expected screen state.',seed=7,inputs=['RIGHT'],expected='player moves right',actual='player remains still',status='failed',evidence=['machine-7'])],findings=[dict(id='finding-1',category='movement',severity='major',certainty='Observed',reproduction='Reset seed 7, press RIGHT for one step.',seed=7,inputs=['RIGHT'],expected='player moves right',actual='player remains still',evidence=['machine-7'],owner='Design Integration and Production Planning',confidence='high')],unverified_questions=[],explanation='The supplied checkpoint does not establish whether this input should move the player; revise the expected outcome before implementation.'))
        self.s.finish_delegation(assignment['id'],'complete','Returned for test-plan clarification.')
        view=self.s.workflow_view(self.i,ref)
        self.assertEqual((view['phase'],view['state']),('middle','active'))
        self.assertEqual(view['artifacts']['required_review_checkpoint'],report['id'])
        revised=self.s.delegate(self.i,self.p['project'],lead,planner,'Revise the movement checkpoint','',mode='test-plan',workflow=ref,phase='middle')
        with self.assertRaises(PermissionError):
            self.s.save_workflow_step(self.i,ref,self.p['project'],planner,'Clarified movement','RIGHT moves the player one cell.',[])
        step=self.s.save_workflow_step(self.i,ref,self.p['project'],planner,'Clarified movement','RIGHT moves the player one cell.',[],review_id=report['id'])
        self.assertEqual(self.s.workflow_view(self.i,ref)['steps'][-1]['review_id'],report['id'])
        self.s.finish_delegation(revised['id'],'complete','Revised checkpoint linked to the failed review.')
        view=self.s.workflow_view(self.i,ref)
        self.assertEqual((view['phase'],view['state']),('implementation','active'))
        self.assertNotIn('required_review_checkpoint',view['artifacts'])
        self.assertTrue(self.s.recovery_check(self.i,self.p['project'])['ok'])

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
        self.assertEqual(len(proposals),5)
        self.assertIn('Studio Lead',titles);self.assertIn('Lead Developer',titles)
        self.assertTrue(all(p['state']=='pending' for p in self.s.view(self.i)['proposals'] if p['kind']=='staff'))

    def test_lead_developer_subtask_limit_is_three(self):
        staff=self.staff();lead=staff['Studio Lead'];developer=staff['Lead Developer'];specialist=staff['Systems designer']
        parent=self.s.delegate(self.i,self.p['project'],lead,developer,'Implement bounded feature','',mode='delivery')
        for index in range(3):
            child=self.s.delegate(self.i,self.p['project'],developer,specialist,'Focused analysis '+str(index),'',mode='analysis',parent=parent['id'])
            self.s.finish_delegation(child['id'],'complete','Focused report.')
        with self.assertRaises(ValueError):
            self.s.delegate(self.i,self.p['project'],developer,specialist,'Fourth task','',mode='analysis',parent=parent['id'])

    def test_delegated_assignments_follow_role_hierarchy_and_are_saved(self):
        staff=self.staff();lead=staff['Studio Lead'];developer=staff['Lead Developer'];designer=staff['Lead Designer'];engine=staff['Systems designer']
        with self.assertRaises(PermissionError):self.s.delegate(self.i,self.p['project'],designer,engine,'Unscoped request')
        with self.assertRaises(PermissionError):self.s.delegate(self.i,self.p['project'],lead,designer,'Wrong assignment mode')
        design=self.s.delegate(self.i,self.p['project'],lead,designer,'Prepare the project design brief','Define goals and acceptance criteria.',mode='design')
        delivery=self.s.delegate(self.i,self.p['project'],lead,developer,'Review implementation plan','Focus on portability.')
        with self.s.db() as cx:
            design_row=dict(cx.execute('SELECT * FROM studio_delegations WHERE id=?',(design['id'],)).fetchone())
            saved=dict(cx.execute('SELECT * FROM studio_delegations WHERE id=?',(delivery['id'],)).fetchone())
            task=dict(cx.execute('SELECT * FROM studio_tasks WHERE id=?',(delivery['task'],)).fetchone())
        self.assertEqual(design_row['assignee'],designer);self.assertEqual(design_row['mode'],'design')
        self.assertEqual(saved['assignee'],developer);self.assertEqual(task['owner'],developer)

    def test_studio_lead_dispatches_a_real_independent_lead_developer_job(self):
        staff=self.staff();lead=staff['Studio Lead'];developer=staff['Lead Developer']
        self.engine.responses=[json.dumps(dict(action='delegate',args=dict(resident=developer,title='Review the proposed update loop',notes='Check whether the design claim is supported.'),note='Assign focused analysis.'))]
        job=self.c.start(dict(institution=self.i,kind='work',project=self.p['project'],resident=lead,objective='Coordinate one technical question.',turns=8))['id']
        row=self.wait(job);self.assertEqual(row['state'],'complete',row['reason'])
        with self.s.db() as cx:
            assignment=dict(cx.execute('SELECT * FROM studio_delegations').fetchone())
            task=dict(cx.execute('SELECT * FROM studio_tasks WHERE id=?',(assignment['task'],)).fetchone())
            assignment_job=dict(cx.execute("SELECT * FROM studio_jobs WHERE kind='assignment'").fetchone())
        delegate_event=next(e for e in self.s.view(self.i)['events'] if e['kind']=='delegate')
        delegate_result=delegate_event['body']['result']
        self.assertEqual(assignment['state'],'complete',assignment);self.assertEqual(assignment['mode'],'lead-developer');self.assertIn('Independent worker',assignment['result'])
        self.assertEqual(task['state'],'done');self.assertGreaterEqual(len([c for c in self.engine.calls if json.loads(c['messages'][-1]['content']).get('assignment')]),2)
        self.assertEqual(assignment_job['state'],'complete',assignment_job);self.assertTrue(delegate_result['independent_worker']);self.assertTrue(delegate_result['can_edit']);self.assertTrue(delegate_result['can_run_tests'])

    def test_playtest_reviewer_is_dispatched_independently_and_cannot_edit(self):
        staff=self.staff();developer=staff['Lead Developer'];reviewer=staff['Playtest reviewer']
        task=self.s.delegate(self.i,self.p['project'],developer,reviewer,'Independently run cartridge tests','Run the current suite and report exact results.',mode='test')
        row=self.c.start(dict(institution=self.i,project=self.p['project'],kind='assignment',assignment_id=task['id']))
        self.assertEqual(row['state'],'queued')
        job=self.wait(row['id']);self.assertEqual(job['state'],'complete',job['reason'])
        assigned=dict(id='test-work',kind='assignment',institution=self.i,project=self.p['project'],settings=json.dumps(dict(actor=reviewer,assignment_id=task['id'],assignment_mode='test')))
        progress=dict(notes='',last_result={})
        with self.assertRaises(PermissionError):self.c.work_action(assigned,progress,dict(action='edit',args=dict(path='tamper.c',text='bad',expected='')))
        self.c.workbench.tests=lambda iid,build:dict(ok=True,tests=3)
        result,_=self.c.work_action(assigned,progress,dict(action='tests',args=dict(build='fixture-build')))
        self.assertTrue(result['ok']);self.assertEqual(result['tests'],3)

    def test_owner_or_captain_can_message_the_autonomous_studio_lead(self):
        lead=self.staff()['Studio Lead']
        owner=self.c.execute(dict(operation='studio_message',institution=self.i,message='Please review the project backlog.'))
        captain=self.c.execute(dict(operation='captain_studio_message',institution=self.i,message='Please report the project state.'))
        owner_job=self.wait(owner['job']);captain_job=self.wait(captain['job'])
        self.assertEqual(owner_job['state'],'complete',owner_job['reason']);self.assertEqual(captain_job['state'],'complete',captain_job['reason'])
        thread=self.c.execute(dict(operation='studio_conversation',institution=self.i,thread=captain['thread']))
        self.assertEqual(thread[0]['sender'],'captain');self.assertEqual(thread[0]['state'],'complete');self.assertTrue(thread[0]['response'])
        self.assertIn('inbox',json.loads(self.engine.calls[-1]['messages'][-1]['content']))

    def test_studio_lead_chooses_project_instead_of_guessing_when_inbox_is_ambiguous(self):
        self.staff();second=self.s.ingest(self.i,'Second game',[('second.c',b'int score;')],dict(kind='fixture'))
        self.c.pause()
        message=self.c.contact(self.i,'captain','Review project priorities.')
        with self.s.db() as cx:
            row=dict(cx.execute('SELECT * FROM studio_jobs WHERE id=?',(message['job'],)).fetchone())
        self.assertEqual(row['project'],'')
        packet=self.c.work_packet(row,json.loads(row['progress']))
        choices=packet['inbox']['available_projects']
        self.assertEqual({p['id'] for p in choices},{self.p['project'],second['project']})
        selected,_=self.c.work_action(row,json.loads(row['progress']),dict(action='select_project',args=dict(project=second['project'])))
        self.assertTrue(selected['selected']);self.assertEqual(row['project'],second['project'])
        with self.s.db() as cx:self.assertEqual(cx.execute('SELECT project FROM studio_jobs WHERE id=?',(message['job'],)).fetchone()[0],second['project'])
        explicitly_routed=self.c.contact(self.i,'owner','Inspect the second game.','Second game')
        self.assertEqual(self.s.message(explicitly_routed['id'])['project'],second['project'])

    def test_completed_resident_work_automatically_curates_pending_learning(self):
        staff=self.staff();developer=staff['Lead Developer'];designer=staff['Lead Designer'];specialist=staff['Systems designer']
        self.s.learn(self.i,self.p['project'],'studio-task:fixture',designer,'institution','A useful test lesson.','Observed in the independent test report.')
        assignment=self.s.delegate(self.i,self.p['project'],developer,specialist,'Read source and verify current test path','Summarize what needs testing.',mode='analysis')
        queued=self.c.start(dict(institution=self.i,project=self.p['project'],kind='assignment',assignment_id=assignment['id']))
        self.assertEqual(queued['state'],'queued');job=self.wait(queued['id']);self.assertEqual(job['state'],'complete',job['reason'])
        with self.s.db() as cx:state=cx.execute('SELECT state FROM studio_learnings').fetchone()[0]
        self.assertEqual(state,'accepted')

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
