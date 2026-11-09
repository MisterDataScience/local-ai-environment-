"""Founding uses real Engine admission and authenticated HTTP, with no weights."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request,urlopen
BASE=Path(__file__).resolve().parents[2];sys.path[:0]=[str(BASE),str(BASE/'payload')]
from model_engine import Engine
from captain_config import upgrade
from model_team import upgrade_team
from text_models import upgrade_text_configuration
from founding import Founding
from commons import Commons
from http_api import Handler
import village


class FoundingGatewayTests(unittest.TestCase):
    def setup_engine(self,root):
        control=root/'control';control.mkdir()
        config=upgrade(upgrade_team(upgrade_text_configuration({'text_model':'qwen3:14b','api_key':'synthetic-owner-key'})))
        engine=Engine(config,control)
        connector=lambda p:village.connect(p,test_encrypted=True)
        engine.commons=Commons(engine,connector=connector);engine.founding=Founding(engine,connector)
        return engine,connector

    def test_real_admission_pauses_for_foreground_and_strips_forged_internal_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();engine,connector=self.setup_engine(root)
            file=root/'conversations.json';file.write_text(json.dumps([{'id':'a','mapping':{'a':{'message':{'id':'a','author':{'role':'user'},'content':{'parts':['Synthetic private history']}}}}}]))
            cx=connector(engine.founding.root);source=village.import_file(cx,engine.founding.root,file,confirm=True)['sha'];cx.close()
            entered=threading.Event()
            def run(messages,route,prompt,body):
                guard=body.get('_founding_turn')
                if guard:
                    entered.set()
                    while not guard.is_set():time.sleep(.01)
                    raise RuntimeError('cancelled')
                return 'Owner response'
            try:
                with patch.object(engine,'run',side_effect=run):
                    job=engine.founding.start(dict(source=source))['id'];self.assertTrue(entered.wait(2))
                    with self.assertRaises(RuntimeError):engine.commons.start({})
                    body=dict(model=engine.captain['model_id'],messages=[dict(role='user',content='Hello')],_founding_turn=object(),_commons_turn=object())
                    self.assertEqual(engine.submit(body).result(3),'Owner response')
                    self.assertNotIn('_founding_turn',body)
                    end=time.monotonic()+3
                    while engine.founding.guard and time.monotonic()<end:time.sleep(.01)
                    self.assertIsNone(engine.founding.active)
                    row=next(r for r in engine.founding.view()['jobs'] if r['id']==job)
                    self.assertEqual(row['state'],'paused');self.assertEqual(engine.founding.view()['items'],[])
            finally:engine.founding.shutdown();engine.commons.shutdown();engine.executor.shutdown();engine.commons.db.close()

    def test_upload_and_review_controls_require_owner_auth_and_start_no_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();engine,connector=self.setup_engine(root)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.engine=engine;server.daemon_threads=True
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
            def post(path,data,key=True):
                headers={'Content-Type':'application/json'}
                if key:headers['Authorization']='Bearer '+engine.config['api_key']
                req=Request(base+path,data=data,headers=headers)
                with urlopen(req,timeout=3) as result:return json.load(result)
            try:
                with patch.object(engine,'submit',side_effect=AssertionError('No inference authorised')):
                    with self.assertRaises(HTTPError):post('/control/village-upload?token=x&offset=0',b'[]',False)
                    token=post('/control/commons',b'{"operation":"founding_upload_begin"}')['upload']
                    result=post('/control/village-upload?token='+token+'&offset=0',b'[]');self.assertEqual(result['offset'],2)
                    view=post('/control/commons',b'{"operation":"founding_view"}');self.assertEqual(view['jobs'],[])
            finally:server.shutdown();server.server_close();engine.founding.shutdown();engine.commons.shutdown();engine.executor.shutdown();engine.commons.db.close()


if __name__=='__main__':unittest.main()
