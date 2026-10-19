"""Finite Commons: real SQLite, deterministic local inference doubles, no private fixtures."""
import concurrent.futures
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE),str(BASE/'payload')]
import village
import village_memory as memory
import commons


class LocalEngine:
    def __init__(self,path,reply=None):
        self.root=path/'control'; self.root.mkdir()
        self.config={'commons':{'max_active_agents':4}}
        self.captain={'enabled':True,'model_id':'local-ai-captain'}
        self.text_models={'local-ai-captain':{'num_ctx':16384}}
        self.mode='max'; self.slots=5; self.reply=reply
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=5)
        self.lock=threading.Lock(); self.calls=[]; self.active=0; self.maximum=0
        self.commons=None

    def mode_status(self): return dict(mode=self.mode,transitioning=False,error=None)
    def parallel_slots(self): return self.slots
    def submit(self,body,commons_turn=None):
        assert self.commons.owns(commons_turn)
        assert body['inference_only'] and not body.get('tools')
        assert body['model']=='local-ai-captain'
        packet=json.loads(body['messages'][-1]['content'])
        def run():
            with self.lock:
                self.calls.append(copy.deepcopy(packet)); self.active+=1; self.maximum=max(self.maximum,self.active)
            try:
                response=self.reply(packet,commons_turn) if self.reply else {'action':'think','text':'An independent idea.'} if packet['independent_opening'] else {'action':'pass'}
                body['_usage']={'total_tokens':20};body['_finish_reason']='stop'
                return json.dumps(response)
            finally:
                with self.lock: self.active-=1
        return self.pool.submit(run)


class CommonsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.engine=LocalEngine(Path(self.temp.name))
        self.connector=lambda root:village.connect(root,test_encrypted=True)
        self.c=commons.Commons(self.engine,connector=self.connector);self.engine.commons=self.c
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.c.shutdown();self.engine.pool.shutdown(wait=True)
        deadline=time.monotonic()+3
        while self.c.live and time.monotonic()<deadline: time.sleep(.01)
        self.c.db.close()

    def wait(self,predicate,timeout=4):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if predicate(): return
            time.sleep(.01)
        self.fail('Commons did not reach its bounded expected state')

    def finished(self,sid):
        self.wait(lambda:self.c.view(sid)['state']!='running' and not self.c.live)
        if self.c.thread: self.c.thread.join(2)

    def new(self,**settings): return self.c.start(settings)['id']

    def resident(self,sid,actor='writer.general'):
        _,data=self.c._session(sid)
        return data,next(r for r in data['residents'] if r['id']==actor)

    def apply(self,sid,actor,action):
        with self.c.lock:
            data,resident=self.resident(sid,actor)
            _,context,actions=self.c._context(sid,data,resident,False)
            self.c._apply(sid,data,resident,action(context),context,list(commons.ACTIONS))
            self.c._save(sid,data)

    def test_fixed_four_slots_rotation_independent_opening_and_no_idle_autostart(self):
        self.assertEqual(self.engine.calls,[])
        gate=threading.Event()
        def reply(packet,guard):
            if packet['independent_opening']:
                gate.wait(2)
                self.assertFalse(any(s['kind']=='room_message' for s in packet['sources']))
                return {'action':'think','text':'Independent opening for '+packet['resident']}
            return {'action':'pass'}
        self.engine.reply=reply
        sid=self.new(turns=16)
        self.wait(lambda:self.engine.active==4)
        self.assertEqual(self.engine.maximum,4)
        gate.set();self.finished(sid)
        self.assertLessEqual(self.engine.maximum,4)
        self.assertEqual({p['resident'] for p in self.engine.calls},set(commons.village.ROLES[i]+'.general' for i in range(5)))
        self.assertTrue(all(p['independent_opening'] for p in self.engine.calls[:4]))
        cx=self.connector(self.c.root)
        try:
            self.assertEqual(cx.execute('SELECT count(*) FROM messages').fetchone()[0],0)
            self.assertEqual(cx.execute('SELECT count(*) FROM lessons').fetchone()[0],0)
            self.assertFalse(memory.exists(cx))
        finally:cx.close()

    def test_pause_stop_restart_and_mode_gate_do_not_auto_resume(self):
        self.engine.mode='normal'
        with self.assertRaises(RuntimeError):self.new()
        self.engine.mode='max';self.engine.slots=4
        with self.assertRaises(RuntimeError):self.new()
        self.engine.slots=5
        def reply(packet,guard):
            while not guard.is_set(): time.sleep(.01)
            raise RuntimeError('Cancelled')
        self.engine.reply=reply
        sid=self.new()
        self.wait(lambda:self.engine.active==4)
        self.c.pause('foreground work')
        self.wait(lambda:not self.c.live)
        self.c.thread.join(2)
        self.assertEqual(self.c.view(sid)['state'],'paused')
        calls=len(self.engine.calls);time.sleep(.1);self.assertEqual(len(self.engine.calls),calls)
        self.engine.reply=None
        self.c.resume(sid);self.finished(sid)
        self.assertGreater(len(self.engine.calls),calls)
        with self.assertRaises(RuntimeError):self.c.resume(sid)

    def test_deadline_and_turn_budget_close_admission_without_another_prompt(self):
        now=[time.monotonic()]
        self.c.clock=lambda:now[0]
        def reply(packet,guard):
            while not guard.is_set():time.sleep(.01)
            raise RuntimeError('Cancelled')
        self.engine.reply=reply
        sid=self.new(minutes=1,turns=12)
        self.wait(lambda:self.engine.active==4)
        now[0]+=61;self.finished(sid)
        view=self.c.view(sid)
        self.assertEqual(view['data']['reason'],'time budget reached')
        self.assertEqual(len(self.engine.calls),4)
        self.engine.reply=None
        sid2=self.new(turns=4);self.finished(sid2)
        self.assertEqual(self.c.view(sid2)['data']['turns'],4)

    def test_private_scopes_disable_research_and_never_expand_grants(self):
        with self.assertRaises(PermissionError):self.new(collections=['private'],web=True)
        with self.assertRaises(PermissionError):self.new(collections=['private'])
        cx=self.connector(self.c.root)
        with cx:cx.execute("INSERT INTO grants VALUES('writer.general','private')")
        cx.close()
        sid=self.new(collections=['general','private'],residents=['writer.general'])
        self.finished(sid)
        self.assertTrue(all('web_search' not in p['actions'] for p in self.engine.calls))

    def test_quarantine_approval_memory_pointer_separation_and_later_retrieval(self):
        sid=self.new();self.finished(sid)
        actor='writer.general'
        self.apply(sid,actor,lambda refs:dict(action='draft',title='A short story',text='A fabricated little village.',kind='markdown',hidden=True,refs=refs[:1]))
        self.apply(sid,actor,lambda refs:dict(action='propose_memory',kind='experience',text='I tried drafting a short story.',title='When starting another creative piece',refs=[r for r in refs if json.loads(self.c.db.execute('SELECT data FROM sources WHERE id=?',(r,)).fetchone()[0])['kind']=='own_event'][:1]))
        draft=self.c.db.execute("SELECT id FROM events WHERE session=? AND kind='draft'",(sid,)).fetchone()[0]
        self.apply(sid,actor,lambda refs:dict(action='propose_library',target=draft,refs=refs[:1]))
        material=self.c.db.execute("SELECT * FROM proposals WHERE session=? AND kind='library'",(sid,)).fetchone()
        self.apply(sid,actor,lambda refs:dict(action='propose_pointer',target=material['id'],text='Find this story next time.',refs=[]))
        rows={r['kind']:dict(r) for r in self.c.db.execute('SELECT * FROM proposals WHERE session=?',(sid,))}
        cx=self.connector(self.c.root)
        self.assertEqual(memory.packet(cx,actor,['general'])['memories'],[])
        cx.close()
        with self.assertRaises(ValueError):self.c.review(rows['library']['id'],'0'*64,'approve')
        with self.assertRaises(ValueError):self.c.review(rows['pointer']['id'],rows['pointer']['digest'],'approve')
        result=self.c.review(rows['library']['id'],rows['library']['digest'],'approve')
        cx=self.connector(self.c.root)
        self.assertEqual(len(memory.document_search(cx,actor,'village',['general'])),1)
        self.assertEqual(memory.packet(cx,actor,['general'])['pointers'],[])
        cx.close()
        self.c.review(rows['pointer']['id'],rows['pointer']['digest'],'approve')
        self.c.review(rows['memory']['id'],rows['memory']['digest'],'approve')
        cx=self.connector(self.c.root)
        self.assertEqual(len(memory.packet(cx,actor,['general'])['pointers']),1)
        self.assertEqual(len(memory.packet(cx,actor,['general'])['memories']),1)
        self.assertEqual(memory.packet(cx,'analyst.general',['general'])['memories'],[])
        self.assertEqual(village.read(cx,actor,result['reference'])['text'],'A fabricated little village.')
        before=cx.execute('SELECT count(*) FROM resident_memories').fetchone()[0];cx.close()
        self.c.review(rows['memory']['id'],rows['memory']['digest'],'approve')
        cx=self.connector(self.c.root);self.assertEqual(cx.execute('SELECT count(*) FROM resident_memories').fetchone()[0],before);cx.close()
        self.c.db.execute('UPDATE sessions SET expires=0 WHERE id=?',(sid,));self.c.db.commit();self.c.expire()
        with self.assertRaises(ValueError):self.c.view(sid)
        cx=self.connector(self.c.root)
        self.assertEqual(len(memory.packet(cx,actor,['general'])['memories']),1)
        self.assertTrue(memory.packet(cx,actor,['general'])['memories'][0]['id'].startswith('memory:'));cx.close()

    def test_no_outsourcing_or_forged_evidence_and_owner_only_hidden_drafts(self):
        sid=self.new();self.finished(sid)
        for action in ('delegate','bash','spawn','approve','external_model','write_library'):
            with self.assertRaises(PermissionError):self.apply(sid,'writer.general',lambda refs,a=action:dict(action=a,text='No'))
        with self.assertRaises(PermissionError):
            self.apply(sid,'writer.general',lambda refs:dict(action='say',text='Forged',refs=['source:guessed']))
        self.apply(sid,'writer.general',lambda refs:dict(action='draft',title='Surprise',text='Hidden from peers.',hidden=True))
        with self.c.lock:
            data,resident=self.resident(sid,'analyst.general')
            messages,_,_=self.c._context(sid,data,resident,False)
            self.assertNotIn('Hidden from peers.',messages[-1]['content'])
            self.c.db.commit()
        self.assertTrue(any('Hidden from peers.' in e['body'] for e in self.c.view(sid)['events']))

    def test_archive_approval_is_distinct_and_never_creates_a_user_assertion(self):
        sid=self.new();self.finished(sid)
        self.apply(sid,'writer.general',lambda refs:dict(action='draft',title='Public source notes',text='Clearly labelled fabricated derived notes.',refs=refs[:1]))
        draft=self.c.db.execute("SELECT id FROM events WHERE session=? AND kind='draft'",(sid,)).fetchone()[0]
        self.apply(sid,'writer.general',lambda refs:dict(action='propose_archive',target=draft,refs=refs[:1]))
        p=self.c.db.execute("SELECT * FROM proposals WHERE session=? AND kind='archive'",(sid,)).fetchone()
        result=self.c.review(p['id'],p['digest'],'approve')
        cx=self.connector(self.c.root)
        self.assertEqual(village.read(cx,'writer.general',result['reference'])['role'],'research')
        self.assertEqual(len(village.search(cx,'writer.general','fabricated')),1)
        with self.assertRaises(ValueError):village.add_lesson(cx,claim='This is a user preference',kind='explicit_preference',citation=result['reference'],specialist_id='writer.general',approval='test')
        cx.close()

    def test_context_inspection_is_exact_and_owner_target_messages_arrive(self):
        sid=self.new();self.finished(sid)
        # Explicitly stage an owner turn for packet inspection without running inference.
        with self.c.lock:
            data,resident=self.resident(sid)
            self.c._event(sid,data,'owner','owner',dict(text='A direct question just for you.'),[],'owner:writer.general')
            self.c._save(sid,data)
            messages,context,_=self.c._context(sid,data,resident,False)
            self.assertIn('A direct question just for you.',messages[-1]['content'])
            event=self.c._event(sid,data,'writer.general','say',dict(text='A short reply.'),context)
            self.c._save(sid,data)
        shown=self.c.why(event)
        supplied={s['id']:s for s in json.loads(messages[-1]['content'])['sources']}
        self.assertEqual(shown['context_supplied'],[supplied[r] for r in context])

    def test_breakout_membership_private_draft_reveal_and_selective_attention(self):
        sid=self.new();self.finished(sid)
        self.apply(sid,'writer.general',lambda refs:dict(action='create_room',title='Story room',members=['reviewer.general']))
        data,writer=self.resident(sid)
        room=writer['room']
        self.apply(sid,'writer.general',lambda refs:dict(action='say',text='A room-specific idea.',room=room))
        with self.c.lock:
            data,analyst=self.resident(sid,'analyst.general')
            packet,_,_=self.c._context(sid,data,analyst,False)
            self.assertNotIn('A room-specific idea.',packet[-1]['content'])
            self.c.db.commit()
        with self.assertRaises(PermissionError):self.apply(sid,'analyst.general',lambda refs:dict(action='follow',room=room))
        self.apply(sid,'reviewer.general',lambda refs:dict(action='follow',room=room))
        self.apply(sid,'writer.general',lambda refs:dict(action='draft',title='Secret scene',text='Keep this scene hidden.',hidden=True))
        draft=self.c.db.execute("SELECT id FROM events WHERE session=? AND kind='draft' ORDER BY rowid DESC",(sid,)).fetchone()[0]
        with self.assertRaises(PermissionError):self.apply(sid,'reviewer.general',lambda refs:dict(action='reveal',target=draft))
        self.apply(sid,'writer.general',lambda refs:dict(action='reveal',target=draft))
        with self.c.lock:
            data,reviewer=self.resident(sid,'reviewer.general')
            packet,_,_=self.c._context(sid,data,reviewer,False)
            self.assertIn('Keep this scene hidden.',packet[-1]['content'])
            self.c.db.commit()

    def test_individual_memory_correction_deletion_and_no_approval_replay_resurrection(self):
        sid=self.new();self.finished(sid)
        self.apply(sid,'writer.general',lambda refs:dict(action='propose_memory',kind='open_thread',text='An unfinished question.',title='For later creative work',refs=refs[:1]))
        p=self.c.db.execute("SELECT * FROM proposals WHERE session=? AND kind='memory'",(sid,)).fetchone()
        result=self.c.review(p['id'],p['digest'],'approve')
        reference=result['reference']
        changed=self.c.execute(dict(operation='correct',reference=reference,digest=p['digest'],claim='A corrected unfinished question.',purpose='Use only in a relevant creative task'))
        inspected=self.c.execute(dict(operation='memories'))
        self.assertEqual(len(inspected['revisions']),2)
        self.assertEqual(inspected['memories'][0]['claim'],'A corrected unfinished question.')
        cx=self.connector(self.c.root)
        self.assertEqual(len(memory.search_memories(cx,'writer.general','corrected',['general'])),1)
        self.assertEqual(memory.search_memories(cx,'reviewer.general','corrected',['general']),[])
        self.assertEqual(cx.execute('SELECT count(*) FROM resident_memory_revisions WHERE reference=?',(reference,)).fetchone()[0],2)
        cx.close()
        with self.assertRaises(ValueError):self.c.execute(dict(operation='delete',reference=reference,digest=p['digest']))
        self.c.execute(dict(operation='delete',reference=reference,digest=changed['digest']))
        self.c.review(p['id'],p['digest'],'approve')
        cx=self.connector(self.c.root)
        self.assertEqual(memory.packet(cx,'writer.general',['general'])['memories'],[])
        self.assertEqual(cx.execute('SELECT count(*) FROM resident_memory_revisions WHERE reference=?',(reference,)).fetchone()[0],0)
        cx.close()

    def test_private_archive_retrieval_stays_in_quarantine_until_separate_approval(self):
        cx=self.connector(self.c.root)
        with cx:
            cx.execute("INSERT INTO grants VALUES('writer.general','private')")
            cx.execute("INSERT INTO imports VALUES('synthetic','test',1,'complete',1,1,NULL)")
            cx.execute("INSERT INTO conversations VALUES('private-thread','Private fixture','1','{}','synthetic')")
            cx.execute("INSERT INTO messages VALUES('msg:private','private-thread','a','','user','1','PRIVATE SYNTHETIC EXCERPT','{}',1,'private')")
            row=cx.execute("SELECT rowid FROM messages WHERE citation='msg:private'").fetchone()[0]
            cx.execute("INSERT INTO message_fts(rowid,text,title) VALUES(?,'PRIVATE SYNTHETIC EXCERPT','Private fixture')",(row,))
        cx.close()
        sid=self.new(collections=['general','private'],residents=['writer.general']);self.finished(sid)
        self.apply(sid,'writer.general',lambda refs:dict(action='read_source',target='msg:private'))
        self.apply(sid,'writer.general',lambda refs:dict(action='propose_memory',kind='open_thread',text='Remember a synthetic private point.',title='Only in this scope',refs=refs[-1:]))
        p=self.c.db.execute('SELECT * FROM proposals WHERE session=?',(sid,)).fetchone()
        self.c.review(p['id'],p['digest'],'approve')
        cx=self.connector(self.c.root)
        self.assertEqual(memory.packet(cx,'writer.general',['general'])['memories'],[])
        self.assertEqual(len(memory.packet(cx,'writer.general',['general','private'])['memories']),1)
        cx.close()
        with self.assertRaises(PermissionError):self.apply(sid,'writer.general',lambda refs:dict(action='web_search',text='PRIVATE SYNTHETIC EXCERPT'))
        cx=self.connector(self.c.root)
        with cx:cx.execute("UPDATE messages SET active=0 WHERE citation='msg:private'")
        self.assertEqual(memory.packet(cx,'writer.general',['general','private'])['memories'],[])
        cx.close()
        self.c.execute(dict(operation='purge',session=sid))
        self.assertEqual(self.c.db.execute('SELECT count(*) FROM sources WHERE session=?',(sid,)).fetchone()[0],0)
        with self.assertRaises(ValueError):self.c.view(sid)
        cx=self.connector(self.c.root)
        self.assertEqual(cx.execute('SELECT count(*) FROM resident_memories').fetchone()[0],1)
        cx.close()

    def test_discussion_evidence_keeps_source_dependencies_after_quarantine_expires(self):
        sid=self.new();self.finished(sid)
        cx=self.connector(self.c.root)
        memory.initialize(cx)
        with cx:cx.execute("INSERT INTO library_documents VALUES('doc:fixture','Fixture','Synthetic source','general','[]','digest','approved',1,'owner')")
        with self.c.lock:
            data,_=self.resident(sid)
            source=self.c._source(sid,'analyst.general','library','doc:fixture','Synthetic source',['general'])
            event=self.c._event(sid,data,'analyst.general','say',{'text':'An interpretation'},[source['id']])
            derivative=self.c._source(sid,'writer.general','room_message',event,'An interpretation',['general'])
            self.assertEqual(derivative['dependencies'],['doc:fixture'])
            self.c._save(sid,data)
        proposal=dict(id='proposal:dependency',actor='writer.general',kind='memory',digest='exact',scopes=['general'],payload=dict(kind='revised_belief',text='A synthetic interpretation',purpose='When revisiting the fixture'))
        result=memory.approve(cx,proposal,[derivative],'owner')
        subsequent=copy.deepcopy(proposal)
        subsequent.update(id='proposal:later-memory',digest='later')
        later=dict(derivative,origin=result['reference'],dependencies=[result['reference']])
        memory.approve(cx,subsequent,[later],'owner')
        self.c.execute(dict(operation='purge',session=sid))
        self.assertEqual(len(memory.packet(cx,'writer.general',['general'])['memories']),2)
        memory.withdraw(cx,'doc:fixture','digest','owner')
        self.assertEqual(memory.packet(cx,'writer.general',['general'])['memories'],[])
        with self.assertRaises(PermissionError):memory.read_memory(cx,'writer.general',result['reference'],['general'])
        cx.close()

    def test_token_budget_stops_without_consuming_unbounded_failed_retries(self):
        sid=self.new(token_budget=4096,turns=48);self.finished(sid)
        self.assertLessEqual(self.c.view(sid)['data']['reserved'],4096)
        self.assertLess(len(self.engine.calls),48)

    def test_source_revision_changes_and_owner_rejections_do_not_create_memories(self):
        sid=self.new();self.finished(sid)
        self.apply(sid,'writer.general',lambda refs:dict(action='propose_memory',kind='open_thread',text='A speculative thread.',title='Review later',refs=refs[:1]))
        p=self.c.db.execute('SELECT * FROM proposals WHERE session=?',(sid,)).fetchone()
        self.c.review(p['id'],p['digest'],'reject')
        cx=self.connector(self.c.root);self.assertFalse(memory.exists(cx));cx.close()
        with self.assertRaises(ValueError):self.c.review(p['id'],p['digest'],'approve')


if __name__=='__main__':unittest.main()
