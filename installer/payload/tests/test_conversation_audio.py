import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conversation_audio as audio
import token_stream
from backend_http import ContextLengthError
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import model_engine
import http_api
from text_models import DEFAULT_TEXT_MODELS


class StreamingTests(unittest.TestCase):
    def test_real_http_delivers_first_token_while_backend_is_still_running(self):
        release = threading.Event()
        class Backend(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                data=b'{"models":[]}'
                self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self_test.assertTrue(payload['stream']); self_test.assertFalse(payload['truncate'])
                self.send_response(200);self.end_headers()
                self.wfile.write(b'{"message":{"content":"First "}}\n');self.wfile.flush()
                release.wait(3)
                self.wfile.write(b'{"message":{"content":"last"},"done":true,"done_reason":"length","eval_count":2,"prompt_eval_count":3}\n');self.wfile.flush()
        self_test=self
        backend=ThreadingHTTPServer(('127.0.0.1',0),Backend)
        threading.Thread(target=backend.serve_forever,daemon=True).start()
        with tempfile.TemporaryDirectory() as directory:
            engine=model_engine.Engine({'api_key':'test','text_models':DEFAULT_TEXT_MODELS,
                'ollama_url':f'http://127.0.0.1:{backend.server_port}'},Path(directory))
            server=ThreadingHTTPServer(('127.0.0.1',0),http_api.Handler);server.engine=engine
            threading.Thread(target=server.serve_forever,daemon=True).start()
            try:
                body={'model':'local-ai','stream':True,'messages':[{'role':'user','content':'hello'}]}
                req=Request(f'http://127.0.0.1:{server.server_port}/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer test'})
                with patch.object(model_engine,'port_open',return_value=False), urlopen(req,timeout=2) as response:
                    first=response.readline().decode()
                    self.assertIn('First ',first);self.assertFalse(release.is_set())
                    release.set(); rest=response.read().decode()
                    self.assertIn('last',rest);self.assertIn('"finish_reason": "length"',rest)
                    self.assertIn('"total_tokens": 5',rest)
                    self.assertNotIn('First ',rest)
            finally:
                release.set();server.shutdown();server.server_close();engine.executor.shutdown()
                backend.shutdown();backend.server_close()

    def test_content_arrives_before_completion_and_calls_remain_structured(self):
        sink = token_stream.Stream()
        first = {'message': {'content': 'Hello ', 'thinking': 'private reasoning'}}
        last = {'message': {'content': 'world', 'tool_calls': [{'function': {'name': 'read', 'arguments': {'path': 'a'}}}]},
                'done': True, 'done_reason': 'stop', 'eval_count': 2, 'prompt_eval_count': 3}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def __iter__(self):
                yield json.dumps(first).encode()
                self_test.assertEqual(sink.events.get_nowait(), {'content': 'Hello '})
                yield json.dumps(last).encode()
        self_test = self
        with patch.object(token_stream, 'urlopen', return_value=Response()) as opening:
            result = token_stream.chat('http://test', {'stream': False}, sink)
        self.assertEqual(result['message']['content'], 'Hello world')
        self.assertEqual(result['message']['tool_calls'], last['message']['tool_calls'])
        self.assertEqual(sink.events.get_nowait(), {'content': 'world'})
        self.assertTrue(json.loads(opening.call_args.args[0].data)['stream'])

    def test_truncated_error_and_cancelled_streams_are_not_successes(self):
        for data in [b'{"message":{"content":"partial"}}\n', b'{"error":"offline"}\n']:
            with patch.object(token_stream, 'urlopen', return_value=io.BytesIO(data)):
                with self.assertRaises(RuntimeError): token_stream.chat('http://test', {}, token_stream.Stream())
        sink = token_stream.Stream(); sink.cancelled.set()
        with self.assertRaises(RuntimeError): sink.send({'content': 'late'})
        self.assertTrue(sink.events.empty())
        error = HTTPError('http://test', 400, '', {}, io.BytesIO(b'{"error":"input length exceeds the context window"}'))
        with patch.object(token_stream, 'urlopen', side_effect=error):
            with self.assertRaises(ContextLengthError): token_stream.chat('http://test', {}, token_stream.Stream())


class ResourceTests(unittest.TestCase):
    def make(self):
        engine = SimpleNamespace(config={'conversation': {'enabled': True}}, mode='normal', mode_transitioning=False,
                                 mode_error=None, root=Path('/unused'))
        manager = audio.Audio(engine)
        manager.control('start')
        return manager

    def test_heavy_job_kills_audio_before_entry_and_keeps_cpu_detector(self):
        manager = self.make()
        stt, tts, vad = Mock(), Mock(), Mock()
        manager.workers.update(stt=stt, tts=tts, vad=vad)
        with manager.model_job(light=True):
            tts.close.assert_not_called()
        with manager.model_job():
            stt.close.assert_called_once(); tts.close.assert_called_once(); vad.close.assert_not_called()
            self.assertTrue(manager.control('heartbeat')['busy'])
            with self.assertRaises(audio.Paused): manager.request({'action': 'transcribe', 'pcm': 'AAAA'}, lambda _: None)
            manager.request({'action': 'detect', 'pcm': 'AAAA'}, lambda _: None)
            vad.request.assert_called_once()
        self.assertFalse(manager.control('heartbeat')['busy'])

    def test_suspend_waits_for_inflight_reader_and_marks_it_paused(self):
        manager = self.make(); entered = threading.Event(); killed = threading.Event(); errors = []
        worker = Mock()
        def read(*_): entered.set(); killed.wait(2); raise OSError('closed')
        worker.request.side_effect = read; worker.close.side_effect = killed.set
        manager.workers['stt'] = worker
        def request():
            try: manager.request({'action': 'transcribe', 'pcm': 'AAAA'}, lambda _: None)
            except Exception as error: errors.append(error)
        thread = threading.Thread(target=request); thread.start(); self.assertTrue(entered.wait(1))
        with manager.model_job():
            self.assertTrue(killed.is_set())
            self.assertEqual(manager.users, 1)
        thread.join(1)
        self.assertIsInstance(errors[0], audio.Paused)
        self.assertEqual(manager.users, 0)

    def test_cancel_retains_idle_tts_and_expiry_releases_everything(self):
        manager = self.make(); worker = Mock(); worker.lock.locked.return_value = False
        manager.workers['tts'] = worker
        manager.control('cancel'); worker.close.assert_not_called()
        worker.lock.locked.return_value = True
        manager.control('cancel'); worker.close.assert_called_once()
        worker = Mock(); manager.workers['stt'] = worker; manager.last_seen = time.monotonic()-21
        manager.expire(); self.assertFalse(manager.enabled); worker.close.assert_called_once()

    def test_busy_worker_is_not_killed_and_failed_load_releases_accounting(self):
        manager = self.make(); worker = Mock(); worker.request.side_effect = audio.Busy('busy')
        manager.workers['stt'] = worker
        with self.assertRaises(audio.Busy): manager.request({'action': 'transcribe', 'pcm': 'AAAA'}, lambda _: None)
        worker.close.assert_not_called(); self.assertEqual(manager.users, 0)
        manager.workers.clear()
        with patch.object(audio, 'Worker', side_effect=OSError('missing')):
            with self.assertRaises(OSError): manager.request({'action': 'transcribe', 'pcm': 'AAAA'}, lambda _: None)
        self.assertEqual(manager.users, 0)


if __name__ == '__main__': unittest.main()
