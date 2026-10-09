"""Exercise the real HTTP boundary for malformed input and inference-only work."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from http_api import Handler
from model_engine import Engine
from model_team import preset


class RequestBoundaryTests(unittest.TestCase):
    def test_non_object_json_returns_400_and_never_admits_inference(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        server.engine = Mock(config={'api_key': 'fixture'})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for body in ([], None, 1, 'text'):
                with self.subTest(body=body):
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                    try:
                        connection.request('POST', '/v1/chat/completions', json.dumps(body),
                            {'Authorization': 'Bearer fixture', 'Content-Type': 'application/json'})
                        response = connection.getresponse()
                        self.assertEqual(response.status, 400)
                        self.assertIn('JSON object', json.loads(response.read())['error']['message'])
                    finally:
                        connection.close()
            server.engine.submit.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_inference_only_refuses_commands_and_tool_definitions(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine({'text_models': {'local-ai': preset('coordinator')}}, Path(directory))
            self.addCleanup(engine.executor.shutdown)
            engine.mode = 'max'
            for command in ('image', 'video', 'search', 'read', 'reverse', 'speak'):
                body = {'model': 'local-ai', 'inference_only': True,
                        'messages': [{'role': 'user', 'content': '/' + command + ' fixture'}]}
                with self.subTest(command=command), patch('model_engine.api') as backend:
                    with self.assertRaisesRegex(ValueError, 'text inference only'):
                        engine.submit(body)
                    backend.assert_not_called()
            body = {'model': 'local-ai', 'inference_only': True, 'messages': [{'role': 'user', 'content': 'fixture'}],
                    'tools': [{'type': 'function', 'function': {'name': 'effectful', 'parameters': {}}}]}
            with self.assertRaisesRegex(ValueError, 'text inference only'):
                engine.submit(body)


if __name__ == '__main__':
    unittest.main()
