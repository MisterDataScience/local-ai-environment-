import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conversation as voice
import conversation_setup


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.app = voice.Conversation(self.root, 'native-secret', {'api_key': 'gateway-secret'})
        self.app.audio = Mock(return_value={'enabled': True, 'busy': False})

    def tearDown(self):
        self.app.active = False; self.app.closed.set(); self.temp.cleanup()

    def test_sentence_chunking_never_waits_for_whole_essay(self):
        chunks, remaining = voice.phrases('First sentence. Next sentence is unfinished')
        self.assertEqual(chunks, ['First sentence.']); self.assertEqual(remaining, 'Next sentence is unfinished')
        chunks, remaining = voice.phrases('word ' * 600, True)
        self.assertTrue(all(len(chunk) <= 280 for chunk in chunks)); self.assertFalse(remaining)

    def test_native_compaction_followups_are_followed_without_speaking_summary(self):
        def message(id, role, parts, **extra):
            return {'info':dict(id=id,role=role,time={'created':10},**extra),'parts':parts}
        turn={'message':'msg_original','input':'Hello','wall_started':5}
        messages=[message('msg_compact','user',[{'type':'compaction','auto':True}]),
                  message('msg_summary','assistant',[{'type':'text','text':'secret summary'}],parentID='msg_compact',summary=True,agent='compaction'),
                  message('msg_continue','user',[{'type':'text','text':'continue','synthetic':True,'metadata':{'compaction_continue':True}}]),
                  message('msg_answer','assistant',[{'type':'text','text':'real answer'}],parentID='msg_continue',agent='plan'),
                  message('msg_unrelated','assistant',[],parentID='msg_other',agent='plan')]
        self.assertEqual([m['info']['id'] for m in voice.response_messages(messages,turn)],['msg_answer'])
        messages += [message('msg_replay','user',[{'type':'text','text':'Hello'}]),
                     message('msg_after','assistant',[],parentID='msg_replay',agent='plan')]
        self.assertIn('msg_after',[m['info']['id'] for m in voice.response_messages(messages,turn)])

    def test_native_session_reply_audio_ack_and_interrupt_ignore_stale_events(self):
        folder = self.root / 'voice-engine/voices'; folder.mkdir(parents=True); (folder / 'default.json').write_text('{}')
        submitted = {}
        def native(path, data=None):
            if path == '/session': return {'id':'ses_test'}
            if path.endswith('/abort'): return True
            if path.endswith('/prompt_async'): submitted.update(data); return None
            if '/message?' in path:
                return [{'info':{'id':'msg_answer','role':'assistant','parentID':submitted['messageID'], 'time':{'created':1,'completed':2}},
                         'parts':[{'id':'prt_text','type':'text','text':'Hello there. How are you?'}]}]
            if path == '/session/status': return {}
            raise AssertionError(path)
        self.app.native = Mock(side_effect=native)
        self.app.start('default')
        data = (json.dumps({'pcm':base64.b64encode(b'\0\0'*240).decode(),'sample_rate':24000})+'\n{"done":true}\n').encode()
        with patch.object(voice, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(data)):
            result = self.app.submit('Hello', 'plan')
            deadline = time.monotonic()+2
            while not any(e['kind']=='done' for e in self.app.events) and time.monotonic()<deadline: time.sleep(.01)
        self.assertTrue(any(e['kind']=='audio' for e in self.app.events))
        self.assertEqual(submitted['agent'], 'plan')
        self.assertEqual(submitted['parts'], [{'type':'text','text':'Hello'}])
        self.app.played({'generation':result['generation'],'chunk':1})
        seconds = self.app.turn['played_seconds']
        self.app.played({'generation':result['generation'],'chunk':1})
        self.assertEqual(seconds,self.app.turn['played_seconds'])
        self.app.played({'generation':result['generation'],'phrase':1})
        self.assertEqual(self.app.turn['played'], ['Hello there.'])
        old = result['generation']; self.app.interrupt()
        self.assertFalse(self.app.emit(old, 'audio', pcm='stale'))
        self.app.played({'generation':old,'phrase':2})
        self.assertEqual(self.app.turn['played'], ['Hello there.'])
        logs = [json.loads(line) for line in self.app.log_path.read_text().splitlines()]
        self.assertEqual(logs[-1]['played_phrases'], ['Hello there.'])
        self.assertNotIn('gateway-secret', self.app.log_path.read_text())

    def test_permissions_restricted_to_conversation_and_native_child(self):
        self.app.session='ses_ours'
        self.app.native = Mock(side_effect=lambda path, data=None:
            [{'id':'ses_child'}] if path.endswith('/children') else
            [{'id':'per_ours','sessionID':'ses_child'},{'id':'per_other','sessionID':'ses_other'}] if path=='/permission' else True)
        self.assertEqual([p['id'] for p in self.app.permissions()], ['per_ours'])
        with self.assertRaises(ValueError): self.app.dispatch('permission', {'id':'per_other','reply':'once'})
        with self.assertRaises(ValueError): self.app.dispatch('permission', {'id':'per_ours','reply':'always'})
        self.app.dispatch('permission', {'id':'per_ours','reply':'once'})
        self.app.native.assert_called_with('/permission/per_ours/reply', {'reply':'once'})

    def test_wire_requires_private_capability_and_exact_origin(self):
        server = ThreadingHTTPServer(('127.0.0.1',0), voice.Handler); server.app=self.app
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for headers, allowed in [({'Host':'127.0.0.1:8003'},False),
                    ({'Host':'evil.example','Authorization':'Bearer '+self.app.key},False),
                    ({'Host':'127.0.0.1:8003','Origin':'https://evil.example','Authorization':'Bearer '+self.app.key},False),
                    ({'Host':'127.0.0.1:8003','Origin':voice.ORIGIN,'Authorization':'Bearer '+self.app.key},True)]:
                req=Request(f'http://127.0.0.1:{server.server_port}/api', data=b'{"action":"poll"}',headers=headers)
                if allowed:
                    with urlopen(req) as response: self.assertFalse(json.load(response)['active'])
                else:
                    with self.assertRaises(HTTPError) as error: urlopen(req)
                    self.assertEqual(error.exception.code,403)
        finally: server.shutdown();server.server_close();thread.join()

    def test_installer_pins_and_checks_all_three_workers(self):
        (self.root/'voice-engine').mkdir()
        run=Mock(); result=conversation_setup.install(self.root,'uv',run)
        self.assertEqual(result['stt_revision'],conversation_setup.STT_REVISION)
        checks=[c for c in run.call_args_list if 'conversation_worker.py' in ' '.join(map(str,c.args[0]))]
        self.assertEqual([c.args[0][2] for c in checks],['vad','stt','tts'])
        self.assertTrue(all(c.kwargs['env']['HF_HUB_OFFLINE']=='1' for c in checks))


if __name__ == '__main__': unittest.main()
