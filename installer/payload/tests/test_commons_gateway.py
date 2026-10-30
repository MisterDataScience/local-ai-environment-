"""Gateway admission and authenticated owner controls, without model weights."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from http.server import ThreadingHTTPServer

BASE=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(BASE),str(BASE/'payload')]
from model_engine import Engine
from captain_config import upgrade
from model_team import upgrade_team
from text_models import upgrade_text_configuration
from http_api import Handler,MediaHandler
import village
from commons import Commons


class GatewayCommonsTests(unittest.TestCase):
    def test_foreground_request_pauses_four_real_gateway_admissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()/'control';root.mkdir()
            config=upgrade(upgrade_team(upgrade_text_configuration({'text_model':'qwen3:14b'})))
            engine=Engine(config,root)
            c=Commons(engine,connector=lambda path:village.connect(path,test_encrypted=True));engine.commons=c
            active=0;lock=threading.Lock();four=threading.Event()
            def run(messages,route,prompt,body):
                nonlocal active
                guard=body.get('_commons_turn')
                if guard:
                    with lock:
                        active+=1
                        if active==4:four.set()
                    try:
                        while not guard.is_set():time.sleep(.01)
                        raise RuntimeError('Commons cancelled for owner')
                    finally:
                        with lock:active-=1
                return 'Owner response'
            try:
                with patch.object(engine,'run',side_effect=run):
                    sid=c.start({})['id']
                    self.assertTrue(four.wait(3))
                    self.assertEqual(engine.model_jobs.status()['active'],4)
                    # Forged internal fields from an ordinary caller are stripped.
                    body=dict(model=config['captain']['model_id'],messages=[{'role':'user','content':'Hello'}],_commons_turn=object())
                    self.assertEqual(engine.submit(body).result(3),'Owner response')
                    self.assertEqual(c.view(sid)['state'],'paused')
                    self.assertNotIn('_commons_turn',body)
                    end=time.monotonic()+3
                    while c.live and time.monotonic()<end:time.sleep(.01)
                    self.assertFalse(c.live)
                    time.sleep(.05)
                    self.assertEqual(c.view(sid)['state'],'paused')
            finally:
                c.shutdown();engine.executor.shutdown();c.db.close()

    def test_static_page_starts_no_inference_and_owner_controls_require_auth(self):
        class EngineStub:
            config={'api_key':'synthetic-only-key'}
            def commons_controller(self):
                raise AssertionError('Unauthorised or static request must not construct a controller')
        engine=EngineStub()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;server.engine=engine
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(base+'/commons',timeout=3) as response:
                page=response.read().decode();self.assertIn('Village Commons',page)
                self.assertIn("connect-src 'self'",response.headers['Content-Security-Policy'])
                self.assertNotIn('synthetic-only-key',page)
            request=Request(base+'/control/commons',data=b'{"operation":"view"}',headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as caught:urlopen(request,timeout=3)
            self.assertEqual(caught.exception.code,401)
            calls=[]
            class Controller:
                def execute(self,payload):calls.append(payload);return {'active':None}
            engine.commons_controller=lambda:Controller()
            request.add_header('Authorization','Bearer synthetic-only-key')
            with urlopen(request,timeout=3) as response:self.assertIsNone(json.load(response)['active'])
            self.assertEqual(calls,[{'operation':'view'}])
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_media_listener_never_exposes_commons_owner_page(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),MediaHandler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with self.assertRaises(HTTPError) as caught:urlopen('http://127.0.0.1:'+str(server.server_port)+'/commons',timeout=3)
            self.assertEqual(caught.exception.code,404)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_studio_page_and_upload_require_owner_auth_without_starting_models(self):
        class Stub:
            config={'api_key':'fixture-key'}
            def studios_controller(self):raise AssertionError('No unauthorised controller construction')
        engine=Stub();server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;server.engine=engine
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(base+'/institutions',timeout=3) as response:
                page=response.read().decode();self.assertIn('Studio Lead',page);self.assertNotIn('fixture-key',page)
            for path in ('/control/studios','/control/studio-upload?token=test&offset=0'):
                with self.assertRaises(HTTPError) as caught:urlopen(Request(base+path,data=b'{}'),timeout=3)
                self.assertEqual(caught.exception.code,401)
            class Controller:
                def execute(self,payload):return {'institutions':[]}
            engine.studios_controller=lambda:Controller()
            request=Request(base+'/control/studios',data=b'{"operation":"view"}',headers={'Authorization':'Bearer fixture-key'})
            with urlopen(request,timeout=3) as response:self.assertEqual(json.load(response),{'institutions':[]})
        finally:server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':unittest.main()
