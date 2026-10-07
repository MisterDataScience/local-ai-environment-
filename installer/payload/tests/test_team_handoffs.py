"""Real gateway HTTP, simulated Ollama: native-client handoff sequencing."""
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_engine import Engine
from http_api import Handler
from model_team import upgrade_team
from text_models import upgrade_text_configuration


class TeamHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = upgrade_team(upgrade_text_configuration({'api_key': 'test'}))
        self.engine = Engine(self.config, Path(self.temp.name))
        self.roles = self.config['model_team']['roles']
        self.loaded = None
        self.events = []
        self.backend = patch('model_engine.api', side_effect=self.api)
        self.backend.start()
        self.ports = patch('model_engine.port_open', return_value=False)
        self.ports.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.engine = self.engine
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.engine.executor.shutdown()
        self.backend.stop()
        self.ports.stop()
        self.temp.cleanup()

    def api(self, base, path, body=None, **kwargs):
        if path == '/api/ps':
            return {'models': [{'name': self.loaded}] if self.loaded else []}
        if path == '/api/generate':
            self.assertEqual(body['keep_alive'], 0)
            self.events.append(('unload', self.loaded))
            self.loaded = None
            return {}
        self.assertEqual(path, '/api/chat')
        self.assertIn(self.loaded, (None, body['model']))
        self.assertFalse(body['truncate'])
        self.assertFalse(body['shift'])
        self.loaded = body['model']
        self.events.append(('inference', self.loaded))
        if body.get('tools') and body['messages'][-1]['role'] == 'user':
            message = {'role': 'assistant', 'content': '', 'tool_calls': [
                {'function': {'name': 'task', 'arguments': {'prompt': 'Bounded task'}}}]}
        else:
            message = {'role': 'assistant', 'content': 'Result'}
        return {'message': message, 'done_reason': 'stop', 'prompt_eval_count': 20, 'eval_count': 5}

    def chat(self, role, messages, tools=None):
        body = {'model': self.roles[role], 'messages': messages, 'max_tokens': 128}
        if tools: body['tools'] = tools
        request = Request(f'http://127.0.0.1:{self.server.server_port}/v1/chat/completions',
                          data=json.dumps(body).encode(), headers={'Authorization': 'Bearer test', 'Content-Type': 'application/json'})
        with urlopen(request, timeout=3) as response:
            result = json.load(response)
        self.assertEqual(result['usage']['total_tokens'], 25)
        return result['choices'][0]['message']

    def test_both_specialists_return_to_parent_without_deadlock_or_overlap(self):
        tools = [{'type': 'function', 'function': {'name': 'task', 'description': 'Bounded task',
                  'parameters': {'type': 'object', 'properties': {'prompt': {'type': 'string'}}}}}]
        for specialist in ('analyst', 'coder'):
            user = {'role': 'user', 'content': 'Use a specialist'}
            parent = self.chat('coordinator', [user], tools)
            result = self.chat(specialist, [{'role': 'user', 'content': 'Focused evidence'}])
            answer = self.chat('coordinator', [user, parent, {'role': 'tool',
                'tool_call_id': parent['tool_calls'][0]['id'], 'content': result['content']}], tools)
            self.assertEqual(answer['content'], 'Result')
        self.assertEqual(sum(event[0] == 'unload' for event in self.events), 4)
        self.assertEqual(sum(event[0] == 'inference' for event in self.events), 6)

    def test_same_weights_different_context_profile_releases_old_runner(self):
        user = [{'role': 'user', 'content': 'Read this text'}]
        self.chat('coordinator', user)
        self.chat('document', user)
        self.assertEqual([kind for kind, model in self.events], ['inference', 'unload', 'inference'])

    def test_unload_failure_prevents_specialist_inference(self):
        self.chat('coordinator', [{'role': 'user', 'content': 'Hello'}])
        body = {'model': self.roles['analyst'], 'messages': [{'role': 'user', 'content': 'Analyse'}]}
        with patch.object(self.engine, 'unload_ollama', side_effect=RuntimeError('unload failed')):
            with self.assertRaisesRegex(RuntimeError, 'unload failed'):
                self.engine.submit(body).result(timeout=2)
        self.assertEqual(sum(event[0] == 'inference' for event in self.events), 1)


if __name__ == '__main__': unittest.main()
