"""Routine management prepares changes without publishing or extra model calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
import village
import village_memory as memory
import resident_management as management
from village_infrastructure import host


class ResidentManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'village';self.cx=village.connect(self.root,test_encrypted=True);self.addCleanup(self.cx.close)
        management.initialize(self.cx)

    def change(self,operation,spec,resident=None):
        payload=dict(operation=operation,spec=spec,reason='A useful recurring specialism')
        if resident:payload['resident']=resident
        with self.cx:return management.prepare(self.cx,'captain',payload)

    def review(self,result,decision='approve'):
        return management.review(self.cx,result['id'],result['digest'],decision)

    def create_spec(self,id='writer.humaniser'):
        return dict(id=id,parent='writer.general',role='writer',tags=['humaniser','editing'],instruction='Use approved humaniser workflow; preserve meaning',status='active')

    def material(self,kind='memory',text='A useful editing procedure',actor='writer.general'):
        p=dict(id='proposal:'+text,actor=actor,kind=kind,digest=text,scopes=['general'],payload=dict(kind='procedure',text=text,purpose='When editing') if kind=='memory' else dict(title='Humaniser workflow',text=text))
        return memory.approve(self.cx,p,[],'owner')['reference']

    def test_five_baseline_roles_need_no_owner_creation_or_empty_map_setup(self):
        self.assertEqual(len(village.status(self.cx)),5)
        self.assertEqual(management.maintain(self.cx),[])
        self.assertEqual(self.cx.execute('SELECT count(*) FROM specialists').fetchone()[0],5)

    def test_system_prepares_map_from_approved_work_without_publishing_it(self):
        ref=self.material();doc=self.material('library','Workflow contents')
        rows=management.maintain(self.cx);self.assertEqual(len(rows),1)
        row=rows[0];p=json.loads(row['payload'])
        self.assertEqual(p['spec']['fast_access'][0]['target'],ref)
        self.assertEqual(p['spec']['preferred_sources'][0]['target'],doc)
        self.assertEqual(memory.packet(self.cx,'writer.general',['general'])['fast_access'],[])
        self.review(row)
        packet=memory.packet(self.cx,'writer.general',['general'])
        self.assertEqual(packet['fast_access'][0]['id'],ref)
        self.assertEqual(packet['preferred_sources'][0]['target'],doc)
        self.assertEqual(management.maintain(self.cx),[])

    def test_rejected_identical_suggestion_is_not_repeated_or_lost_into_memory(self):
        self.material();first=management.maintain(self.cx)[0]
        self.assertEqual(management.maintain(self.cx)[0]['id'],first['id'])
        self.review(first,'reject')
        self.assertEqual(management.maintain(self.cx),[])
        self.assertEqual(memory.starting_map(self.cx,'writer.general')['revision'],0)
        self.material(text='Another useful procedure')
        self.assertEqual(len(management.maintain(self.cx)),1)

    def test_valid_pins_stay_selected_and_corrections_are_prepared_for_separate_approval(self):
        ref=self.material();row=management.maintain(self.cx)[0];self.review(row)
        old=memory.starting_map(self.cx,'writer.general')['revision']
        memory.correct(self.cx,ref,'A useful editing procedure','A corrected procedure','When editing','owner')
        pending=management.maintain(self.cx)
        self.assertEqual(memory.starting_map(self.cx,'writer.general')['revision'],old)
        self.assertEqual(memory.packet(self.cx,'writer.general',['general'])['fast_access'],[])
        self.review(pending[0]);self.assertEqual(memory.packet(self.cx,'writer.general',['general'])['fast_access'][0]['claim'],'A corrected procedure')
        for i in range(4):self.material(text='Additional procedure '+str(i))
        later=management.maintain(self.cx)[0];self.review(later)
        self.assertEqual(memory.packet(self.cx,'writer.general',['general'])['fast_access'][0]['id'],ref)

    def test_profile_creation_revision_and_retirement_require_owner_review(self):
        create=self.change('create',self.create_spec())
        self.assertEqual(len(village.status(self.cx)),5)
        self.review(create)
        self.assertEqual(village.specialist(self.cx,'writer.humaniser')['status'],'active')
        self.assertEqual(village.route(self.cx,'writer','humaniser text'),'writer.humaniser')
        rev=self.change('revise',dict(id='writer.humaniser',tags=['humaniser','style'],instruction='Follow the approved style guide'))
        self.assertEqual(village.packet(self.cx,'writer.humaniser')['revision'],1)
        self.review(rev);self.assertEqual(village.packet(self.cx,'writer.humaniser')['revision'],2)
        retirement=self.change('retire',dict(id='writer.humaniser'));self.review(retirement)
        self.assertEqual(village.route(self.cx,'writer','humaniser text'),'writer.general')
        self.review(retirement) # durable receipt, no repeat state change

    def test_stale_parent_or_map_content_fails_closed(self):
        create=self.change('create',self.create_spec())
        with self.cx:self.cx.execute("DELETE FROM grants WHERE specialist_id='writer.general' AND collection_id='general'")
        with self.assertRaises(PermissionError):self.review(create)
        with self.cx:self.cx.execute("INSERT INTO grants VALUES('writer.general','general')")
        ref=self.material();row=management.maintain(self.cx)[0]
        memory.correct(self.cx,ref,'A useful editing procedure','A different procedure','When editing','owner')
        with self.assertRaises(ValueError):self.review(row)
        self.assertEqual(memory.starting_map(self.cx,'writer.general')['revision'],0)
        with self.assertRaises(ValueError):management.review(self.cx,row['id'],'wrong','approve')

    def test_no_self_approval_built_in_retirement_private_expansion_or_new_permissions(self):
        for operation,spec in [('approve',{}),('retire',dict(id='writer.general')),('create',dict(self.create_spec(),collections=['private'])),('create',dict(self.create_spec(),tools=['bash'])),('create',dict(self.create_spec(),role='coder'))]:
            with self.assertRaises((ValueError,PermissionError)):self.change(operation,spec)
        with self.assertRaises(PermissionError):
            self.change('map',dict(fast_access=[],glossary=[],preferred_sources=[dict(target='archive:private',label='Private',query='secrets')]),'writer.general')
        self.assertEqual(len(village.status(self.cx)),5)

    def test_host_envelope_assigns_captain_identity_and_replay_is_atomic(self):
        payload=dict(operation='create',spec=self.create_spec(),reason='Recurring editing work')
        envelope=dict(operation='manage',project='a'*64,identity='researcher.general',revision=1,actor='captain',task='',request_id='b'*64,payload=payload)
        result=host(self.cx,self.root,envelope)
        self.assertEqual(host(self.cx,self.root,envelope),result)
        altered=copy.deepcopy(envelope);altered['payload']['reason']='Changed'
        with self.assertRaises(ValueError):host(self.cx,self.root,altered)
        worker=copy.deepcopy(envelope);worker.update(actor='researcher.general',task='child',request_id='c'*64)
        with self.assertRaises(PermissionError):host(self.cx,self.root,worker)
        self.assertEqual(len(village.status(self.cx)),5)

    def test_pending_expiry_removes_content_without_publishing(self):
        result=self.change('create',self.create_spec())
        with self.cx:self.cx.execute('UPDATE resident_changes SET expires=0 WHERE id=?',(result['id'],))
        self.assertEqual(management.maintain(self.cx),[])
        with self.assertRaises(ValueError):self.review(result)
        self.assertEqual(len(village.status(self.cx)),5)


if __name__=='__main__':unittest.main()
