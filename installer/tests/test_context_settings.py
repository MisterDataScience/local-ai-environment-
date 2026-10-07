import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import context_settings as settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.values = {'task.model.params': {'temperature': 0.2, 'max_tokens': 9999},
                       'unrelated.setting': 'preserved'}
        self.calls = []
        self.reject = False
        self.confirm = True
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def handle_request(self):
                size = int(self.headers.get('Content-Length', '0'))
                body = json.loads(self.rfile.read(size)) if size else None
                owner.calls.append((self.path, body, self.headers.get('Authorization')))
                if self.path.endswith('/signin'):
                    result = {'token': 'test-session-token'}
                elif owner.reject:
                    self.send_error(401)
                    return
                elif self.headers.get('Authorization') != 'Bearer test-session-token':
                    self.send_error(403)
                    return
                elif self.path.endswith('/import'):
                    owner.values.update(body['config'])
                    result = owner.values
                elif self.path.endswith('/task'):
                    result = {k: v for k, v in owner.values.items() if k.startswith('task.')}
                else:
                    result = {k: v for k, v in owner.values.items() if k.startswith('chat.')} if owner.confirm else {}
                data = json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = patch.object(settings, 'BASE', f'http://127.0.0.1:{self.server.server_port}')
        self.base.start()

    def tearDown(self):
        self.base.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def test_native_api_mode_update_preserves_other_settings_and_avoids_repeat_writes(self):
        manager = settings.ContextSettings()
        policy = {'mode': 'normal', 'threshold': 8192, 'summary_tokens': 1024}
        with patch.dict(os.environ, {'HTTP_PROXY': 'http://127.0.0.1:1'}):
            self.assertTrue(manager.sync(policy))
        self.assertEqual(self.calls[0], ('/api/v1/auths/signin', {'email': 'admin@localhost', 'password': ''}, None))
        self.assertEqual(self.values['unrelated.setting'], 'preserved')
        self.assertEqual(self.values['task.model.params'], {'temperature': 0.2, 'max_tokens': 1024})
        self.assertEqual(self.values['chat.context_compaction.model'], '')
        count = len(self.calls)
        self.assertFalse(manager.sync(copy.deepcopy(policy)))
        self.assertEqual(len(self.calls), count)
        policy.update(mode='gaming', threshold=1536, summary_tokens=512)
        self.assertTrue(manager.sync(policy))
        self.assertEqual(self.values['chat.context_compaction.token_cap'], 1536)
        self.assertEqual(self.values['task.model.params']['max_tokens'], 512)

    def test_expired_session_and_failed_verification_are_not_marked_applied(self):
        manager = settings.ContextSettings()
        policy = {'mode': 'normal', 'threshold': 8192, 'summary_tokens': 1024}
        self.reject = True
        with self.assertRaises(RuntimeError):
            manager.sync(policy)
        self.assertIsNone(manager.applied)
        self.assertIsNone(manager.token)
        self.reject = False
        self.confirm = False
        with self.assertRaises(RuntimeError):
            manager.sync(policy)
        self.assertIsNone(manager.applied)
        self.confirm = True
        self.assertTrue(manager.sync(policy))

    def test_unknown_endpoints_and_redirects_are_refused(self):
        with self.assertRaises(ValueError):
            settings.local_api('/outside')
        self.assertIsNone(settings.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))
