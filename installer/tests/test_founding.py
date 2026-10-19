"""Founding review runs local, bounded inference doubles over real private fixtures."""
import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'payload')]
import village
import village_memory as memory
import founding


class LocalReviewEngine:
    def __init__(self,root):
        self.root=root/'control';self.root.mkdir();self.mode='max'
        self.captain=dict(enabled=True,model_id='local-ai-captain');self.text_models={'local-ai-captain':dict(num_ctx=16384)}
        self.commons=None;self.founding=None;self.calls=[];self.reply=None;self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=2)
    def mode_status(self):return dict(mode=self.mode,transitioning=False,error=None)
    def submit(self,body,founding_turn=None):
        assert self.founding.owns(founding_turn) and body['inference_only'] and not body.get('tools')
        sources=json.loads(body['messages'][-1]['content']);self.calls.append(sources)
        def run():
            if self.reply:return self.reply(sources,founding_turn)
            evidence=[dict(citation=s['citation'],quote=s['text'][:80]) for s in sources[:2]]
            common=dict(role='coder',tags=['r'],certainty='explicit',evidence=evidence,when='When writing R',category='workflows')
            return json.dumps(dict(items=[dict(common,kind='library',title='R workflow',text='Use base R for these tasks.'),dict(common,kind='memory',title='R procedure',text='Use base R when appropriate.',memory_kind='procedure'),dict(common,kind='preference',title='Owner R preference',text='The owner prefers base R.')]))
        return self.pool.submit(run)


class FoundingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.engine=LocalReviewEngine(self.root);self.connector=lambda path:village.connect(path,test_encrypted=True)
        self.f=founding.Founding(self.engine,self.connector);self.engine.founding=self.f;self.addCleanup(self.cleanup)
        self.file=self.root/'conversations.json'
        self.file.write_text(json.dumps([dict(id='chat-'+str(i),title='R work '+str(i),mapping={'a':dict(parent=None,message=dict(id='a',author={'role':'user'},content=dict(parts=['PRIVATE_MARKER Please use base R for my code. '+str(i)])))}) for i in range(2)]))
        cx=self.connector(self.f.root);self.receipt=village.import_file(cx,self.f.root,self.file,confirm=True);cx.close()
    def cleanup(self):self.f.shutdown();self.engine.pool.shutdown(wait=True)
    def done(self,job):
        end=time.monotonic()+4
        while time.monotonic()<end:
            view=self.f.view();row=next(r for r in view['jobs'] if r['id']==job)
            if row['state']!='running' and self.f.guard is None:
                if self.f.thread:self.f.thread.join(1)
                return row
            time.sleep(.01)
        self.fail('Bounded review did not finish')
    def start(self,**settings):return self.f.start(dict(source=self.receipt['sha'],**settings))['id']

    def test_raw_preserved_and_extracts_profiles_memories_stay_pending_until_exact_approval(self):
        self.assertEqual(self.engine.calls,[])
        job=self.start();self.assertEqual(self.done(job)['state'],'complete')
        self.assertEqual((self.f.root/'archive'/(self.receipt['sha']+'.json')).read_bytes(),self.file.read_bytes())
        view=self.f.view();self.assertEqual({r['kind'] for r in view['items']},{'library','memory','preference','specialist'})
        cx=self.connector(self.f.root)
        self.assertEqual(len(village.status(cx)),5);self.assertEqual(memory.document_search(cx,'coder.general','R',['general']),[])
        for item in view['items']:
            preview=founding.preview_item(cx,item['id'])
            with self.assertRaises(ValueError):founding.publish_item(cx,self.f.root,item['id'],'wrong','general','approve')
            result=founding.publish_item(cx,self.f.root,item['id'],preview['digest'],'general','approve')
            self.assertEqual(founding.publish_item(cx,self.f.root,item['id'],preview['digest'],'general','approve'),result)
        self.assertEqual(len(village.status(cx)),6)
        self.assertEqual(village.route(cx,'coder','r code'),'coder.r')
        own=memory.search_memories(cx,'coder.general','base R',['general']);self.assertEqual(len(own),1)
        self.assertNotIn('PRIVATE_MARKER',memory.read_memory(cx,'coder.general',own[0]['citation'],['general'])['text'])
        self.assertTrue(list((self.f.root/'library/workflows').glob('*.md')))
        self.assertTrue((self.f.root/'library/README.md').exists());cx.close()

    def test_budget_extension_is_explicit_and_cursor_resumes_without_reimport(self):
        cx=self.connector(self.f.root)
        with cx:cx.execute("UPDATE messages SET text=?",('Long synthetic passage. '*1500,))
        cx.close();self.engine.reply=lambda sources,guard:'{"items":[]}'
        job=self.start(turns=1);row=self.done(job);self.assertEqual(row['state'],'budget');self.assertEqual(len(self.engine.calls),1)
        with self.assertRaises(ValueError):self.f.resume(job)
        self.f.control('founding_extend',dict(job=job));self.assertEqual(len(self.engine.calls),1)
        self.f.resume(job);row=self.done(job);self.assertEqual(row['state'],'complete');self.assertGreater(len(self.engine.calls),1)

    def test_pause_cancel_and_restart_never_auto_resume(self):
        entered=threading.Event()
        def blocking(sources,guard):
            entered.set()
            while not guard.is_set():time.sleep(.01)
            raise RuntimeError('cancelled')
        self.engine.reply=blocking;job=self.start();self.assertTrue(entered.wait(2));self.f.pause('Foreground work');self.done(job)
        calls=len(self.engine.calls);time.sleep(.05);self.assertEqual(len(self.engine.calls),calls)
        restarted=founding.Founding(self.engine,self.connector);self.assertIsNone(restarted.active)
        self.engine.reply=lambda sources,guard:'{"items":[]}';self.f.resume(job);self.assertEqual(self.done(job)['state'],'complete')

    def test_one_bounded_format_repair_runs_without_owner_reprompting(self):
        count=[0]
        def repair(sources,guard):
            count[0]+=1
            return 'invalid JSON' if count[0]==1 else '```json\n{"items":[]}\n```'
        self.engine.reply=repair;job=self.start();self.assertEqual(self.done(job)['state'],'complete')
        self.assertEqual(count[0],2);self.assertEqual(self.f.view()['chunks'],[])

    def test_no_remote_provider_no_normal_mode_and_no_delegation_path(self):
        self.engine.mode='normal'
        with self.assertRaises(RuntimeError):self.start()
        self.engine.mode='max';self.engine.ollama='https://example.com'
        with self.assertRaises(PermissionError):self.start()
        with self.assertRaises(ValueError):self.f.control('delegate',{})
        self.assertEqual(self.engine.calls,[])

    def test_forged_quotes_assistant_preferences_and_borrowed_experiences_rejected_atomically(self):
        cx=self.connector(self.f.root)
        sources=[dict(citation='msg:fake',role='assistant',text='An assistant claim')]
        packet=dict(sources=sources)
        common=dict(kind='preference',title='Fake',text='A preference',role='writer',tags=[],certainty='explicit',evidence=[dict(citation='msg:fake',quote='An assistant')])
        with self.assertRaises(ValueError):founding.items_from_response(cx,'none',packet,json.dumps(dict(items=[common])))
        common.update(kind='memory',memory_kind='experience',certainty='inferred')
        with self.assertRaises(ValueError):founding.items_from_response(cx,'none',packet,json.dumps(dict(items=[common])))
        common.update(memory_kind='procedure');common['evidence'][0]['quote']='FORGED'
        with self.assertRaises(PermissionError):founding.items_from_response(cx,'none',packet,json.dumps(dict(items=[common])))
        self.assertEqual(cx.execute('SELECT count(*) FROM founding_items').fetchone()[0],0);cx.close()

    def test_failure_stays_unreviewed_until_retry_or_explicit_skip(self):
        self.engine.reply=lambda sources,guard:'not JSON';job=self.start();row=self.done(job)
        self.assertEqual(row['state'],'paused');self.assertIn('failed',row['reason'])
        self.assertTrue(self.f.view()['chunks'])
        self.f.control('founding_skip',dict(job=job));self.engine.reply=lambda sources,guard:'{"items":[]}'
        self.f.resume(job);row=self.done(job);self.assertIn('skipped passages: 1',row['reason'])
        self.f.control('founding_forget',dict(job=job));self.assertEqual(self.f.view()['jobs'],[])
        self.assertTrue((self.f.root/'archive'/(self.receipt['sha']+'.json')).exists())

    def test_upload_is_append_only_private_and_imports_with_one_explicit_start(self):
        token=self.f.upload_begin()['upload'];data=self.file.read_bytes();mid=len(data)//2
        self.assertEqual(self.f.upload(token,0,data[:mid])['offset'],mid)
        with self.assertRaises(ValueError):self.f.upload(token,0,b'wrong offset')
        with self.assertRaises(ValueError):self.f.upload('../escape',0,b'no')
        self.f.upload(token,mid,data[mid:])
        job=self.f.start(dict(upload=token))['id'];self.done(job)
        self.assertFalse((self.f.root/'jobs'/token).exists())

    def test_owner_only_library_publication_does_not_expand_resident_grants(self):
        job=self.start();self.done(job);item=next(r for r in self.f.view()['items'] if r['kind']=='library')
        cx=self.connector(self.f.root);p=founding.preview_item(cx,item['id'],'private')
        founding.publish_item(cx,self.f.root,item['id'],p['digest'],'private','approve')
        self.assertEqual(village.grants(cx,'coder.general'),{'general'})
        self.assertEqual(memory.document_search(cx,'coder.general','R',['general']),[])
        cx.close()


if __name__=='__main__':unittest.main()
