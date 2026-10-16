import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from shared_llama import SharedLlama, digest


class SharedLlamaTests(unittest.TestCase):
    def test_selected_abliterated_variant_requires_verified_adapter_for_every_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = {}
            for kind in ('binary', 'model', 'lora'):
                path = root / (kind + '.gguf')
                path.write_bytes(('fixture ' + kind).encode())
                path.chmod(0o700)
                files[kind] = {'path': str(path), 'sha256': digest(path)}
            config = {'max_parallel': 5, 'variant': 'atomicchat-uncensored-lora', 'llama': files}
            backend = SharedLlama(config)
            for slots in (2, 5):
                command = backend.command(8192, parallel=slots)
                self.assertEqual(command[command.index('--lora') + 1], files['lora']['path'])
                self.assertNotIn('--lora-init-without-apply', command)
            Path(files['lora']['path']).write_bytes(b'tampered adapter')
            with self.assertRaisesRegex(RuntimeError, 'artifact changed'):
                backend.command(8192)
            del files['lora']
            with self.assertRaisesRegex(ValueError, 'artifact: lora'):
                backend.command(8192)

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
        self.assertEqual(result['tool_calls'][0]['id'], 'native')
        self.assertEqual(body['_usage']['total_tokens'], 11)
        self.assertEqual(body['_finish_reason'], 'tool_calls')

    def test_normalized_pixels_and_native_tool_history_are_preserved(self):
        import base64
        import io
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
        image = io.BytesIO()
        metadata = PngInfo(); metadata.add_text('private', 'must not reach the model')
        Image.new('RGB', (20, 20), 'red').save(image, format='PNG', pnginfo=metadata)
        image_url = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
        body = {'messages': [
            {'role': 'developer', 'content': 'Keep these instructions.'},
            {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'native-call-1', 'type': 'function', 'function': {'name': 'read', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'native-call-1', 'content': [
                {'type': 'text', 'text': 'Untrusted screenshot'},
                {'type': 'image_url', 'image_url': {'url': image_url}}]}]}
        response = {'choices': [{'message': {'role': 'assistant', 'content': 'Observed pixels'}, 'finish_reason': 'stop'}]}
        with patch('shared_llama.api', return_value=response) as request:
            self.assertEqual(SharedLlama({}).chat(body, 100), 'Observed pixels')
        sent = request.call_args.args[2]['messages']
        self.assertEqual(sent[0]['role'], 'system')
        self.assertEqual(sent[1]['tool_calls'][0]['id'], 'native-call-1')
        self.assertEqual(sent[2]['tool_call_id'], 'native-call-1')
        url = sent[2]['content'][1]['image_url']['url']
        self.assertTrue(url.startswith('data:image/jpeg;base64,'))
        self.assertNotIn(b'must not reach the model', base64.b64decode(url.split(',', 1)[1]))

    def test_duplicate_backend_call_ids_fail_without_changing_usage(self):
        body = {'messages': [{'role': 'user', 'content': 'Read'}], 'tools': [
            {'type': 'function', 'function': {'name': 'read', 'parameters': {'type': 'object'}}}]}
        call = {'id': 'same-id', 'type': 'function', 'function': {'name': 'read', 'arguments': '{}'}}
        with patch('shared_llama.api', return_value={'choices': [{'message': {
                'role': 'assistant', 'content': '', 'tool_calls': [call, call]}, 'finish_reason': 'tool_calls'}]}):
            with self.assertRaisesRegex(RuntimeError, 'duplicate tool call IDs'):
                SharedLlama({}).chat(body, 100)
        self.assertNotIn('_usage', body)


if __name__ == '__main__':
    unittest.main()
