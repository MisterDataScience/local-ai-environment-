"""Wire-level regressions for native client context management."""
import concurrent.futures
import io
import json
from pathlib import Path
import sys
import threading
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_http
import http_api
import model_engine
from text_models import DEFAULT_TEXT_MODELS, output_ceiling


class ContextProtocolTests(unittest.TestCase):
    def test_reply_limits_preserve_small_summary_requests_and_mode_caps(self):
        self.assertEqual(model_engine.output_limit({'max_tokens': 1000}), 1000)
        self.assertEqual(model_engine.output_limit({'max_completion_tokens': 500}), 500)
        self.assertEqual(model_engine.output_limit({'max_tokens': 800, 'max_completion_tokens': 400}), 400)
        self.assertEqual(model_engine.output_limit({'max_tokens': 9999}), 8192)
        for mode, ceiling in [('gaming', 1024), ('normal', 4096), ('max', 8192)]:
            self.assertEqual(model_engine.output_limit({}, mode), ceiling)
            self.assertEqual(model_engine.output_limit({'max_tokens': 99999}, mode), ceiling)
            self.assertEqual(model_engine.output_limit({'max_tokens': 32}, mode), 32)
        self.assertEqual(output_ceiling('max', {'num_ctx': 4096}), 2048)
        for value in (0, -1, True, 1.5, '100', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                model_engine.output_limit({'max_tokens': value})

    def test_engine_cutoff_reason_reaches_json_and_sse_without_changing_text(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({'api_key': 'test-key', 'text_models': DEFAULT_TEXT_MODELS}, Path(directory))
            server = ThreadingHTTPServer(('127.0.0.1', 0), http_api.Handler)
            server.engine = engine
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for reason, expected in [('length', 'length'), ('stop', 'stop'), (None, 'stop')]:
                    for stream in (False, True):
                        with self.subTest(reason=reason, stream=stream):
                            def backend(base, path, payload=None, timeout=30):
                                if path == '/api/ps':
                                    return {'models': []}
                                self.assertEqual(payload['options']['num_predict'], 7)
                                self.assertFalse(payload['stream'])
                                self.assertFalse(payload['truncate'])
                                self.assertFalse(payload['shift'])
                                return {'message': {'content': 'unfinished essay'}, 'done_reason': reason,
                                        'prompt_eval_count': 20, 'eval_count': 7}
                            body = {'model': 'local-ai', 'stream': stream, 'max_completion_tokens': 7,
                                    'truncate': True, 'shift': True,
                                    '_finish_reason': 'injected', 'usage_workflow': 'coder',
                                    '_accounting_usage': {'prompt_tokens': 9999, 'completion_tokens': 9999},
                                    'messages': [{'role': 'user', 'content': 'Write an essay'}]}
                            request = Request(f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                                data=json.dumps(body).encode(), headers={'Authorization': 'Bearer test-key',
                                    'X-Local-AI-Workflow': 'essay'})
                            def streaming(base, payload, sink):
                                result = backend(base, '/api/chat', payload)
                                sink.send({'content': result['message']['content']})
                                return result
                            with patch.object(model_engine, 'api', side_effect=backend), \
                                 patch.object(model_engine.token_stream, 'chat', side_effect=streaming), \
                                 patch.object(model_engine, 'port_open', return_value=False), \
                                 urlopen(request, timeout=2) as response:
                                text = response.read().decode()
                            if stream:
                                chunks = [json.loads(line[6:]) for line in text.splitlines()
                                          if line.startswith('data: ') and line != 'data: [DONE]']
                                self.assertIsNone(chunks[0]['choices'][0]['finish_reason'])
                                self.assertEqual(chunks[0]['choices'][0]['delta']['content'], 'unfinished essay')
                                result = chunks[-1]
                            else:
                                result = json.loads(text)
                                self.assertEqual(result['choices'][0]['message']['content'], 'unfinished essay')
                            self.assertEqual(result['choices'][0]['finish_reason'], expected)
                            self.assertEqual(result['usage']['completion_tokens'], 7)
                usage_url = f'http://127.0.0.1:{server.server_port}/control/usage'
                with self.assertRaises(HTTPError) as denied:
                    urlopen(usage_url, timeout=2)
                self.assertEqual(denied.exception.code, 401)
                with urlopen(Request(usage_url, headers={'Authorization': 'Bearer test-key'}), timeout=2) as response:
                    report = json.load(response)
                self.assertEqual(report['totals']['requests'], 6)
                self.assertEqual(report['totals']['measured_prompt_tokens'], 120)
                self.assertEqual(report['totals']['measured_completion_tokens'], 42)
                self.assertEqual(report['totals']['cutoff_requests'], 2)
                self.assertEqual(report['workflows'][0]['workflow'], 'essay')
                self.assertEqual(report['workflows'][0]['source'], 'client')
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)
                engine.executor.shutdown()

    def test_actual_backend_options_follow_mode_and_preserved_custom_context(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({'text_models': DEFAULT_TEXT_MODELS}, Path(directory))
            try:
                for mode, expected, context in [('gaming', 1024, 4096), ('normal', 4096, 16384), ('max', 8192, 16384)]:
                    engine.mode = mode
                    body = {'model': 'local-ai-small', 'max_tokens': 99999,
                            'messages': [{'role': 'user', 'content': 'Write an essay'}]}
                    with patch.object(model_engine, 'port_open', return_value=False), \
                         patch.object(model_engine, 'api', side_effect=[{'models': []},
                             {'message': {'content': 'essay'}, 'done_reason': 'length'}]) as backend:
                        engine.submit(body).result(2)
                    options = backend.call_args.args[2]['options']
                    self.assertEqual(options['num_ctx'], context)
                    self.assertEqual(options['num_predict'], expected)
                    self.assertEqual(body['_finish_reason'], 'length')
                engine.text_models['local-ai-small']['num_ctx'] = 4096
                with patch.object(model_engine, 'port_open', return_value=False), \
                     patch.object(model_engine, 'api', side_effect=[{'models': []}, {'message': {'content': 'essay'}}]) as backend:
                    engine.submit(body).result(2)
                self.assertEqual(backend.call_args.args[2]['options']['num_predict'], 2048)
            finally:
                engine.executor.shutdown()

    def test_only_explicit_backend_context_errors_are_classified(self):
        for message, expected in [('input length exceeds the context window', backend_http.ContextLengthError),
                                  ('the prompt is longer than the context length currently available to the model', backend_http.ContextLengthError),
                                  ('request (9000 tokens) exceeds the available context size (4096 tokens)', backend_http.ContextLengthError),
                                  ('model not found', RuntimeError)]:
            error = HTTPError('http://localhost/api/chat', 400, 'bad request', {},
                              io.BytesIO(json.dumps({'error': message}).encode()))
            with patch.object(backend_http, 'urlopen', side_effect=error):
                with self.assertRaises(expected) as caught:
                    backend_http.api('http://localhost', '/api/chat', {})
            self.assertEqual(type(caught.exception), expected)

    def test_wire_errors_and_usage_for_streaming_and_json_clients(self):
        engine = Mock(config={'api_key': 'test-key'})
        server = ThreadingHTTPServer(('127.0.0.1', 0), http_api.Handler)
        server.engine = engine
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for failure in (None, RuntimeError('backend offline'), backend_http.ContextLengthError('too big')):
                for stream in (False, True):
                    with self.subTest(failure=failure, stream=stream):
                        def submit(body, stream=None):
                            future = concurrent.futures.Future()
                            if failure:
                                future.set_exception(failure)
                            else:
                                body['_usage'] = {'prompt_tokens': 120, 'completion_tokens': 30, 'total_tokens': 150}
                                future.set_result('answer')
                            return future
                        engine.submit.side_effect = submit
                        request = Request(f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                            data=json.dumps({'model': 'local-ai', 'messages': [], 'stream': stream}).encode(),
                            headers={'Authorization': 'Bearer test-key', 'Content-Type': 'application/json'})
                        try:
                            response = urlopen(request, timeout=2)
                        except HTTPError as error:
                            response = error
                        with response:
                            status, text = response.status, response.read().decode()
                        if stream:
                            events = [json.loads(line[6:]) for line in text.splitlines()
                                      if line.startswith('data: ') and line != 'data: [DONE]']
                            result = events[-1]
                            self.assertEqual(status, 200)
                            if failure:
                                self.assertEqual(len(events), 1)
                                self.assertNotIn('choices', result)
                        else:
                            result = json.loads(text)
                            self.assertEqual(status, 400 if isinstance(failure, backend_http.ContextLengthError)
                                             else 502 if failure else 200)
                        if failure:
                            self.assertEqual(result['error']['code'], 'context_length_exceeded'
                                             if isinstance(failure, backend_http.ContextLengthError) else 'backend_error')
                            self.assertNotIn('Local generation failed:', text)
                        else:
                            self.assertEqual(result['usage']['total_tokens'], 150)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

