"""Owner-curated memory navigation; real storage, no model or private user data."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
import village
import village_memory as memory


class StartingMapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cx=village.connect(Path(self.temp.name)/'village',test_encrypted=True);self.addCleanup(self.cx.close)
        memory.initialize(self.cx)
        self.sid='writer.general'
        self.old=self.remember('Old humaniser editing lesson')
        self.new=self.remember('Recent unrelated idea')
        self.doc=memory.approve(self.cx,dict(id='proposal:doc',actor=self.sid,kind='library',digest='doc-digest',scopes=['general'],payload=dict(title='Humaniser workflow',text='FULL WORKFLOW BODY humaniser')),[],'owner')['reference']
        with self.cx:
            self.cx.execute("INSERT INTO imports VALUES('fixture','test',1,'complete',1,1,NULL)")
            self.cx.execute("INSERT INTO conversations VALUES('fixture-thread','Humaniser examples','1','{}','fixture')")
            self.cx.execute("INSERT INTO messages VALUES('msg:fixture','fixture-thread','a','','user','1','Humaniser archive example','{}',1,'general')")
            row=self.cx.execute("SELECT rowid FROM messages WHERE citation='msg:fixture'").fetchone()[0]
            self.cx.execute("INSERT INTO message_fts(rowid,text,title) VALUES(?,'Humaniser archive example','Humaniser examples')",(row,))

    def remember(self,claim,scopes=None,actor=None):
        return memory.approve(self.cx,dict(id='proposal:'+claim,actor=actor or self.sid,kind='memory',digest=claim,scopes=scopes or ['general'],payload=dict(kind='procedure',text=claim,purpose='When editing')),[],'owner')['reference']

    def spec(self):
        return dict(fast_access=[dict(target=self.old,label='Editing principle',when='Before rewriting')],
                    glossary=[dict(target='memories',label='Deeper editing experiences',query='humaniser')],
                    preferred_sources=[dict(target=self.doc,label='Humaniser workflow',when='When humanising text'),
                                       dict(target='archive:general',label='Writing examples',query='humaniser')])

    def approve(self,spec=None,sid=None):
        sid=sid or self.sid;p=memory.preview_map(self.cx,sid,self.spec() if spec is None else spec)
        memory.approve_map(self.cx,sid,p['spec'],p['digest'],'owner reviewed')
        return p

    def test_explicit_layers_choose_old_memory_without_recency_fallback(self):
        self.assertEqual(memory.packet(self.cx,self.sid,['general'])['fast_access'],[])
        self.assertEqual(len(memory.search_memories(self.cx,self.sid,'idea',['general'])),1)
        p=memory.preview_map(self.cx,self.sid,self.spec())
        self.assertEqual(memory.starting_map(self.cx,self.sid)['revision'],0)
        self.assertEqual(memory.packet(self.cx,self.sid,['general'])['preferred_sources'],[])
        self.approve()
        packet=memory.packet(self.cx,self.sid,['general'])
        self.assertEqual(packet['fast_access'][0]['id'],self.old)
        self.assertNotIn('Recent unrelated idea',json.dumps(packet))
        self.assertIn('map:Humaniser workflow',json.dumps(packet))
        self.assertNotIn('FULL WORKFLOW BODY',json.dumps(packet))
        self.assertEqual(len(packet['glossary']),1)
        self.assertEqual(len(packet['preferred_sources']),2)
        self.assertEqual(village.packet(self.cx,self.sid)['personal'],packet)

    def test_follow_opens_workflow_and_searches_own_memory_or_exact_archive_area(self):
        self.approve()
        self.assertEqual(village.read(self.cx,self.sid,'map:Humaniser workflow')['citation'],self.doc)
        memories=village.read(self.cx,self.sid,'map:Deeper editing experiences')
        self.assertEqual([r['citation'] for r in memories],[self.old])
        archive=village.read(self.cx,self.sid,'map:Writing examples')
        self.assertEqual([r['citation'] for r in archive],['msg:fixture'])
        spec=self.spec();spec['preferred_sources']=[dict(target='library:general',label='Workflow shelf',query='humaniser')]
        self.approve(spec)
        self.assertEqual([r['citation'] for r in village.read(self.cx,self.sid,'map:Workflow shelf')],[self.doc])
        with self.assertRaises(PermissionError):village.read(self.cx,'analyst.general','map:Workflow shelf')

    def test_approval_digest_binds_content_base_revision_and_target_revision(self):
        p=memory.preview_map(self.cx,self.sid,self.spec())
        changed=copy.deepcopy(p['spec']);changed['fast_access'][0]['when']='Different use'
        with self.assertRaises(ValueError):memory.approve_map(self.cx,self.sid,changed,p['digest'],'owner')
        memory.correct(self.cx,self.old,'Old humaniser editing lesson','Corrected lesson','When editing','owner')
        with self.assertRaises(ValueError):memory.approve_map(self.cx,self.sid,p['spec'],p['digest'],'owner')
        self.approve()
        fresh=memory.preview_map(self.cx,self.sid,self.spec());self.approve()
        with self.assertRaises(ValueError):memory.approve_map(self.cx,self.sid,fresh['spec'],fresh['digest'],'owner')
        self.assertEqual(memory.starting_map(self.cx,self.sid)['revision'],2)

    def test_correction_withdrawal_and_source_changes_hide_entries_until_owner_reapproval(self):
        self.approve()
        memory.correct(self.cx,self.old,'Old humaniser editing lesson','Corrected lesson','When editing','owner')
        self.assertEqual(memory.packet(self.cx,self.sid,['general'])['fast_access'],[])
        with self.assertRaises(PermissionError):village.read(self.cx,self.sid,'map:Editing principle')
        self.approve();self.assertEqual(len(memory.packet(self.cx,self.sid,['general'])['fast_access']),1)
        memory.withdraw(self.cx,self.doc,'doc-digest','owner')
        self.assertEqual(len(memory.packet(self.cx,self.sid,['general'])['preferred_sources']),1)
        with self.assertRaises(PermissionError):village.read(self.cx,self.sid,'map:Humaniser workflow')
        with self.cx:self.cx.execute("UPDATE messages SET collection='private' WHERE citation='msg:fixture'")
        # General area still exists, but its search cannot retrieve a moved private source.
        self.assertEqual(village.read(self.cx,self.sid,'map:Writing examples'),[])

    def test_private_maps_never_expand_scope_or_transfer_another_agents_memories(self):
        with self.cx:self.cx.execute("INSERT INTO grants VALUES(?, 'private')",(self.sid,))
        private=self.remember('Private synthetic memory',['private'])
        spec=dict(fast_access=[dict(target=private,label='Private lesson')],glossary=[dict(target='memories',label='Private topics',query='synthetic',collections=['private'])],preferred_sources=[dict(target='archive:private',label='Private archive area',query='synthetic')])
        self.approve(spec)
        general=memory.packet(self.cx,self.sid,['general'])
        self.assertEqual(general['fast_access']+general['glossary']+general['preferred_sources'],[])
        with self.assertRaises(PermissionError):village.read(self.cx,self.sid,'map:Private lesson')
        self.assertEqual(village.read(self.cx,self.sid,'map:Private lesson',request_collections=['private'])['citation'],private)
        with self.assertRaises(PermissionError):self.approve(spec,'analyst.general')
        with self.cx:self.cx.execute("DELETE FROM grants WHERE specialist_id=? AND collection_id='private'",(self.sid,))
        self.assertEqual(memory.packet(self.cx,self.sid,['private'])['fast_access'],[])
        with self.assertRaises(PermissionError):self.approve(spec)

    def test_invalid_foreign_pending_targets_unknown_fields_and_navigation_budget_fail(self):
        for target in ('/etc/passwd','https://example.com','doc:pending','memory:missing','archive:missing'):
            spec=self.spec();spec['preferred_sources'][0]['target']=target
            with self.assertRaises((ValueError,PermissionError)):self.approve(spec)
        other=self.remember('Another agent memory',actor='analyst.general')
        spec=self.spec();spec['fast_access'][0]['target']=other
        with self.assertRaises(PermissionError):self.approve(spec)
        spec=self.spec();spec['glossary'][0]['label']='Editing principle'
        with self.assertRaises(ValueError):self.approve(spec)
        spec=self.spec();spec['fast_access']*=4
        with self.assertRaises(ValueError):self.approve(spec)
        spec=self.spec();spec['glossary'][0]['query']=''
        with self.assertRaises(ValueError):self.approve(spec)
        spec=self.spec();spec['grant']='private'
        with self.assertRaises(ValueError):self.approve(spec)
        large=dict(fast_access=[],glossary=[dict(target='memories',label='g'+str(i),query='a'*159+str(i),when='b'*160) for i in range(8)],preferred_sources=[dict(target='library:general',label='s'+str(i),query='a'*159+str(i),when='b'*160) for i in range(6)])
        with self.assertRaisesRegex(ValueError,'5,000-byte'):self.approve(large)
        with self.assertRaises(ValueError):memory.approve_map(self.cx,self.sid,self.spec(),'wrong','')
        self.assertEqual(memory.starting_map(self.cx,self.sid)['revision'],0)

    def test_v1_migration_preserves_material_and_failed_migration_rolls_back(self):
        with self.cx:
            self.cx.execute('DROP TABLE resident_starting_map_revisions')
            self.cx.execute('DROP TABLE resident_starting_maps')
            self.cx.execute('UPDATE resident_memory_schema SET version=1')
        self.assertEqual(memory.packet(self.cx,self.sid,['general'])['fast_access'],[])
        original=memory._map_schema
        def broken(cx):original(cx);raise RuntimeError('injected migration failure')
        with patch.object(memory,'_map_schema',side_effect=broken):
            with self.assertRaises(RuntimeError):memory.initialize(self.cx)
        self.assertEqual(self.cx.execute('SELECT version FROM resident_memory_schema').fetchone()[0],1)
        self.assertFalse(memory._has_maps(self.cx))
        memory.initialize(self.cx)
        self.assertEqual(self.cx.execute('SELECT version FROM resident_memory_schema').fetchone()[0],2)
        self.assertEqual(memory.document_read(self.cx,self.sid,self.doc,['general'])['text'],'FULL WORKFLOW BODY humaniser')
        self.assertEqual(len(memory.search_memories(self.cx,self.sid,'lesson',['general'])),1)
        with self.cx:self.cx.execute('UPDATE resident_memory_schema SET version=99')
        with self.assertRaises(RuntimeError):memory.initialize(self.cx)

    def test_owner_clear_preserves_history_and_deeper_search_without_resurrection(self):
        self.approve()
        empty={k:[] for k in memory.MAP_LIMITS};self.approve(empty)
        self.assertEqual(memory.packet(self.cx,self.sid,['general'])['fast_access'],[])
        self.assertEqual(len(memory.starting_map(self.cx,self.sid)['revisions']),2)
        self.assertEqual(len(memory.search_memories(self.cx,self.sid,'humaniser',['general'])),1)
        memory.delete(self.cx,self.old,'Old humaniser editing lesson','owner')
        with self.assertRaises(PermissionError):self.approve()
        self.assertEqual(memory.starting_map(self.cx,self.sid)['revision'],2)


if __name__=='__main__':unittest.main()
