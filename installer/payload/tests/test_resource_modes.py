import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_engine import Engine
from text_models import DEFAULT_TEXT_MODELS
from http_api import Handler, MediaHandler
import resource_modes


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = Engine({'api_key': 'test', 'text_models': DEFAULT_TEXT_MODELS}, self.root)
        self.backend = patch('model_engine.api', return_value={'models': []})
        self.api = self.backend.start()
        self.ports = patch('model_engine.port_open', return_value=False)
        self.ports.start()

    def tearDown(self):
        self.engine.executor.shutdown()
        self.backend.stop()
        self.ports.stop()
        self.temp.cleanup()

    def switch(self, mode):
        self.engine.change_mode(mode)
        self.engine.executor.submit(lambda: None).result(timeout=2)
        self.assertFalse(self.engine.mode_status()['transitioning'])
        self.assertIsNone(self.engine.mode_status()['error'])

    def body(self, model='local-ai-small', prompt='Hello'):
        return {'model': model, 'messages': [{'role': 'user', 'content': prompt}]}

    def test_gaming_enforcement_and_no_eager_loading(self):
        self.switch('gaming')
        self.assertEqual(list(self.engine.visible_models()), ['local-ai-small'])
        for body in [self.body('local-ai'), self.body('local-ai-large'), self.body(prompt='/image test'), self.body(prompt='/video test')]:
            with self.assertRaises(ValueError):
                self.engine.submit(body)
        self.engine.check_policy(self.body(), 'search')
        self.engine.check_policy(self.body(), 'read')
        self.assertTrue(all(call.args[1] != '/api/chat' for call in self.api.call_args_list))
        self.assertEqual(resource_modes.load(self.root), 'gaming')

    def test_normal_and_max_eligibility(self):
        self.switch('normal')
        self.assertEqual(set(self.engine.visible_models()), {'local-ai', 'local-ai-small'})
        self.engine.check_policy(self.body('local-ai'), 'image')
        with self.assertRaises(ValueError):
            self.engine.check_policy(self.body(), 'video')
        self.switch('max')
        self.assertEqual(len(self.engine.visible_models()), 3)
        self.engine.check_policy(self.body('local-ai-large'), 'video')

    def test_coordinator_media_uses_serial_route_and_rejects_stale_mode(self):
        self.switch('normal')
        token = f'{self.engine.instance_id}:{self.engine.mode_epoch}:normal'
        with patch.object(self.engine, 'render', return_value='asset-link') as render:
            body = self.body(prompt='/image landscape')
            body['media_mode_token'] = token
            self.assertEqual(self.engine.submit(body).result(timeout=2), 'asset-link')
            render.assert_called_once_with('image', 'landscape')
            for prompt, supplied in [('/image landscape', 'stale'), ('Hello', token), ('/video scene', token)]:
                body = self.body(prompt=prompt)
                body['media_mode_token'] = supplied
                with self.assertRaises(ValueError): self.engine.submit(body)
            self.assertEqual(render.call_count, 1)
        self.switch('max')
        body = self.body(prompt='/image landscape')
        body['media_mode_token'] = token
        with self.assertRaisesRegex(ValueError, 'mode changed'): self.engine.submit(body)

    def test_preset_name_cannot_disguise_heavy_model(self):
        self.engine.text_models['local-ai-small']['model'] = 'qwen3:30b-a3b'
        with self.assertRaises(ValueError):
            self.engine.change_mode('gaming')

    def test_active_job_drains_queued_job_invalidated_and_new_jobs_blocked(self):
        started, finish = threading.Event(), threading.Event()
        def running(*args):
            started.set()
            if not finish.wait(3):
                raise RuntimeError('test timeout')
            return 'done'
        with patch.object(self.engine, 'run', side_effect=running) as run:
            active = self.engine.submit(self.body('local-ai-large'))
            self.assertTrue(started.wait(1))
            queued = self.engine.submit(self.body('local-ai-large'))
            self.engine.change_mode('gaming')
            self.assertTrue(self.engine.mode_status()['transitioning'])
            with self.assertRaises(RuntimeError):
                self.engine.submit(self.body())
            finish.set()
            self.assertEqual(active.result(2), 'done')
            with self.assertRaises(RuntimeError):
                queued.result(2)
            self.engine.executor.submit(lambda: None).result(2)
            self.assertEqual(run.call_count, 1)
            self.assertFalse(self.engine.mode_status()['transitioning'])

    def test_failed_release_remains_blocked_and_can_retry(self):
        with patch.object(self.engine, 'unload_ollama', side_effect=RuntimeError('offline')):
            self.engine.change_mode('gaming')
            self.engine.executor.submit(lambda: None).result(2)
        self.assertIsNotNone(self.engine.mode_status()['error'])
        with self.assertRaises(RuntimeError):
            self.engine.submit(self.body())
        self.switch('gaming')

    def test_failed_audio_release_records_a_recoverable_error_instead_of_sticking_in_transition(self):
        with patch.object(self.engine.audio, 'control', side_effect=RuntimeError('Audio process did not release')):
            self.engine.change_mode('gaming')
            self.engine.executor.submit(lambda: None).result(2)
        status = self.engine.mode_status()
        self.assertFalse(status['transitioning'])
        self.assertIsNotNone(status['error'])
        with self.assertRaises(RuntimeError):
            self.engine.submit(self.body())
        self.switch('gaming')

    def test_gaming_bounds_actual_inference_options(self):
        self.switch('gaming')
        self.api.side_effect = lambda url, path, *args, **kw: {'models': []} if path == '/api/ps' else {'message': {'content': 'answer'}}
        self.assertEqual(self.engine.submit(self.body()).result(2), 'answer')
        payload = next(c.args[2] for c in self.api.call_args_list if c.args[1] == '/api/chat')
        self.assertEqual(payload['model'], 'qwen3:4b')
        self.assertLessEqual(payload['options']['num_ctx'], 4096)
        self.assertEqual(payload['options']['num_predict'], 1024)
        self.assertLessEqual(payload['keep_alive'], 120)

    def test_active_render_stops_on_mode_change(self):
        import shutil
        from unittest.mock import Mock
        shutil.copytree(Path(__file__).resolve().parents[1] / 'workflows', self.root / 'workflows')
        self.engine.process = Mock()
        self.engine.process.poll.return_value = None
        def backend(url, path, *args, **kwargs):
            if path == '/prompt':
                return {'prompt_id': 'job'}
            if path.startswith('/history/'):
                self.engine.change_mode('gaming')
                return {}
            return {'models': []}
        self.api.side_effect = backend
        with patch.object(self.engine, 'start_comfy'), patch.object(self.engine, 'stop_comfy') as stop, patch('model_engine.time.sleep'):
            future = self.engine.submit(self.body(prompt='/image test'))
            with self.assertRaisesRegex(RuntimeError, 'Render cancelled'):
                future.result(2)
            self.engine.executor.submit(lambda: None).result(2)
            self.assertGreaterEqual(stop.call_count, 2)
            self.assertFalse(self.engine.mode_status()['transitioning'])

    def test_actual_token_counts_return_to_request_owner(self):
        self.api.side_effect = lambda url, path, *args, **kw: {'models': []} if path == '/api/ps' else {
            'message': {'content': 'answer'}, 'prompt_eval_count': 120, 'eval_count': 8}
        body = self.body('local-ai')
        body['_usage'] = {'total_tokens': 999999}
        self.assertEqual(self.engine.submit(body).result(2), 'answer')
        self.assertEqual(body['_usage'], {'prompt_tokens': 120, 'completion_tokens': 8, 'total_tokens': 128})

    def test_http_auth_and_model_filtering_and_media_isolation(self):
        self.switch('gaming')
        for handler in (Handler, MediaHandler):
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            server.engine = self.engine
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/control/mode')
                self.assertEqual(error.exception.code, 401 if handler is Handler else 404)
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/control/context')
                self.assertEqual(error.exception.code, 401 if handler is Handler else 404)
                if handler is Handler:
                    with urlopen(Request(base + '/control/context', headers={'Authorization': 'Bearer test'})) as r:
                        self.assertEqual(json.load(r)['threshold'], 1536)
                    with urlopen(Request(base + '/v1/models', headers={'Authorization': 'Bearer test'})) as r:
                        self.assertEqual([x['id'] for x in json.load(r)['data']], ['local-ai-small'])
                    with urlopen(Request(base + '/control/mode', data=b'{"mode":"normal"}', headers={'Authorization': 'Bearer test'})) as r:
                        self.assertEqual(r.status, 202)
                else:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + '/control/context', headers={'Authorization': 'Bearer test'}))
                    self.assertEqual(error.exception.code, 404)
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + '/control/mode', data=b'{"mode":"max"}', headers={'Authorization': 'Bearer test'}))
                    self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                t.join(2)

if __name__ == '__main__':
    unittest.main()

