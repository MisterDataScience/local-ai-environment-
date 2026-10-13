import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from shared_llama import SharedLlama, digest


class SharedLlamaTests(unittest.TestCase):
    def test_context_is_per_slot_files_are_verified_and_server_stays_loopback(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'llama-server'; binary.write_text('native executable'); binary.chmod(0o755)
            model = Path(folder) / 'weights.gguf'; model.write_bytes(b'GGUF-weights')
            backend = SharedLlama({'max_parallel': 5, 'llama': {
                'binary': {'path': str(binary), 'sha256': digest(binary)},
                'model': {'path': str(model), 'sha256': digest(model)}}})
            command = backend.command(8192)
            self.assertEqual(command[command.index('--ctx-size') + 1], '40960')
            self.assertEqual(command[command.index('--kv-unified-per-slot') + 1], '8192')
            self.assertEqual(command[command.index('--host') + 1], '127.0.0.1')
            self.assertIn('--no-context-shift', command)
            self.assertIn('true', backend.command(8192, thinking=True)[-1])
            model.write_bytes(b'changed weights')
            with self.assertRaisesRegex(RuntimeError, 'artifact changed'):
                backend.command(8192)

    def test_tool_calls_and_real_usage_are_translated_with_no_hidden_tool_loop(self):
        backend = SharedLlama({})
        body = {'messages': [{'role': 'user', 'content': 'Read a file'}], 'tools': [
            {'type': 'function', 'function': {'name': 'read', 'parameters': {'type': 'object'}}}]}
        response = {'choices': [{'message': {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'native', 'type': 'function', 'function': {'name': 'read', 'arguments': '{"filePath":"a.py"}'}}]},
                                'finish_reason': 'tool_calls'}], 'usage': {'prompt_tokens': 8, 'completion_tokens': 3}}
        with patch('shared_llama.api', return_value=response) as request:
            result = backend.chat(body, 512)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result['tool_calls'][0]['function']['name'], 'read')
        self.assertEqual(body['_usage']['total_tokens'], 11)
        self.assertEqual(body['_finish_reason'], 'tool_calls')


if __name__ == '__main__':
    unittest.main()
