"""Wire-level regressions for native client context management."""
import concurrent.futures
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_http
import http_api
import model_engine


class ContextProtocolTests(unittest.TestCase):
    def test_reply_limits_preserve_small_summary_requests_and_mode_caps(self):
        self.assertEqual(model_engine.output_limit({'max_tokens': 1000}), 1000)
        self.assertEqual(model_engine.output_limit({'max_completion_tokens': 500}), 500)
        self.assertEqual(model_engine.output_limit({'max_tokens': 800, 'max_completion_tokens': 400}), 400)
        self.assertEqual(model_engine.output_limit({'max_tokens': 9999}), 2048)
        self.assertEqual(model_engine.output_limit({'max_tokens': 9999}, True), 1024)
        for value in (0, -1, True, 1.5, '100', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                model_engine.output_limit({'max_tokens': value})

    def test_only_explicit_backend_context_errors_are_classified(self):
        for message, expected in [('input length exceeds the context window', backend_http.ContextLengthError),
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
                        def submit(body):
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
