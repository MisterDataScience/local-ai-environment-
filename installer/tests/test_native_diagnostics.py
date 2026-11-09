import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import diagnose_captain
from native_diagnostics import capture, diagnostic_path
from turnkey_install import ReadinessError
from shared_llama import MINICPM_REPOSITORY, REASONING_PROTOCOL_INSTRUCTION, SharedLlama


def response(content='Python is a programming language.', reasoning='Choose one sentence.', finish='stop'):
    return {'choices': [{'message': {'role': 'assistant', 'content': content,
             'reasoning_content': reasoning}, 'finish_reason': finish}], 'usage': {'completion_tokens': 28}}


class NativeDiagnosticsTests(unittest.TestCase):
    def test_reasoning_only_reply_stays_failed_and_keeps_original_response(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = response(content='')
            with self.assertRaisesRegex(ReadinessError, 'no final answer'):
                capture(root, 'text-local-ai-captain', 'local-ai-captain', {'thinking': True},
                        lambda: raw, prompt='Fixed fixture')
            path = diagnostic_path(root, 'text-local-ai-captain')
            saved = json.loads(path.read_text())
            self.assertEqual(saved['issue'], 'reasoning_without_final_answer')
            self.assertEqual(saved['status'], 'failed')
            self.assertEqual(saved['response'], raw)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_cutoff_is_not_accepted_even_with_some_final_text(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ReadinessError, 'cut off'):
                capture(Path(folder), 'text', 'local-ai', {}, lambda: response(finish='length'), prompt='Fixed')
            saved = json.loads(diagnostic_path(folder, 'text').read_text())
            self.assertEqual(saved['issue'], 'output_cutoff')
            self.assertEqual(saved['response']['choices'][0]['finish_reason'], 'length')

    def test_residency_failure_is_distinct_from_generation_and_response_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            def fail():
                raise ReadinessError('Unexpected resident model')
            with self.assertRaisesRegex(ReadinessError, 'Unexpected resident model'):
                capture(Path(folder), 'text', 'local-ai', {}, lambda: response(), prompt='Fixed', residency=fail)
            saved = json.loads(diagnostic_path(folder, 'text').read_text())
            self.assertEqual(saved['stage'], 'residency')
            self.assertEqual(saved['issue'], 'residency_check_failed')
            self.assertTrue(saved['response']['choices'][0]['message']['content'])

    def test_request_error_does_not_disclose_exception_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            def fail():
                raise RuntimeError('credential-must-not-appear')
            with self.assertRaises(ReadinessError) as caught:
                capture(Path(folder), 'text', 'local-ai', {}, fail, prompt='Fixed')
            saved = diagnostic_path(folder, 'text').read_text()
            self.assertNotIn('credential-must-not-appear', saved + str(caught.exception))

    def test_success_is_recorded_only_after_residency_and_excludes_extra_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            raw = dict(response(), api_key='credential-must-not-appear')
            content, path = capture(Path(folder), 'text', 'local-ai', {'thinking': True},
                lambda: raw, prompt='Fixed', residency=lambda: {'primary': []})
            saved = json.loads(path.read_text())
            self.assertEqual(saved['status'], 'passed')
            self.assertEqual(saved['residency'], {'primary': []})
            self.assertEqual(saved['final_chars'], len(content))
            self.assertNotIn('credential-must-not-appear', path.read_text())

    def test_probe_uses_one_inference_and_does_not_change_config_or_receipts(self):
        for raw in (response(), response(content='')):
            with self.subTest(final=raw['choices'][0]['message']['content']), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); (root / 'control').mkdir()
                config = {'api_key': 'must-not-save', 'captain': {'enabled': True, 'provider': 'llama',
                    'model_id': 'local-ai-captain'}, 'text_models': {'local-ai-captain': {'num_ctx': 16384, 'thinking': True}}}
                config_path = root / 'control/config.json'
                original = json.dumps(config); config_path.write_text(original)
                receipt = root / 'acceptance-report.json'; receipt.write_text('{"checks":[]}')
                backend = Mock()
                def translated(body, limit, transport):
                    native = transport('http://127.0.0.1:11437', '/v1/chat/completions', {
                        'model':'local-ai-captain', 'messages':body['messages'], 'stream':False,
                        'max_tokens':limit, 'cache_prompt':True})
                    body['_finish_reason'] = native['choices'][0]['finish_reason']
                    return native['choices'][0]['message']
                backend.chat.side_effect = translated
                with patch.object(diagnose_captain, 'port_open', return_value=False), \
                     patch.object(diagnose_captain, 'SharedLlama', return_value=backend), \
                     patch.object(diagnose_captain, 'api', return_value=copy.deepcopy(raw)) as request, \
                     patch('sys.stdout', new_callable=io.StringIO) as output:
                    result = diagnose_captain.diagnose(root)
                self.assertEqual(result, 0 if raw['choices'][0]['message']['content'] else 1)
                self.assertEqual(request.call_count, 1)
                backend.start.assert_called_once_with(16384, thinking=True, parallel=1)
                backend.stop.assert_called_once()
                self.assertEqual(config_path.read_text(), original)
                self.assertEqual(receipt.read_text(), '{"checks":[]}')
                self.assertNotIn('must-not-save', output.getvalue())

    def test_probe_refuses_busy_services(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(diagnose_captain, 'port_open', return_value=True), \
                 patch.object(diagnose_captain, 'SharedLlama') as backend:
                with self.assertRaisesRegex(ReadinessError, 'no running service was stopped'):
                    diagnose_captain.diagnose(Path(folder))
                backend.assert_not_called()

    def test_probe_records_the_production_minicpm_system_instruction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'control').mkdir()
            config = {'api_key': 'must-not-save',
                'captain': {'enabled': True, 'provider': 'llama', 'model_id': 'local-ai-captain',
                            'llama': {'model': {'repository': MINICPM_REPOSITORY}}},
                'text_models': {'local-ai-captain': {'num_ctx': 16384, 'thinking': True}}}
            (root / 'control/config.json').write_text(json.dumps(config))
            backend = SharedLlama(config['captain'])
            def start(*args, **kwargs):
                backend.running_thinking = kwargs['thinking']
            with patch.object(diagnose_captain, 'port_open', return_value=False), \
                 patch.object(diagnose_captain, 'SharedLlama', return_value=backend), \
                 patch.object(backend, 'start', side_effect=start), patch.object(backend, 'stop'), \
                 patch.object(diagnose_captain, 'api', return_value=response()) as request, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(diagnose_captain.diagnose(root), 0)
            self.assertEqual(request.call_count, 1)
            sent = request.call_args.args[2]
            self.assertEqual(sent['messages'][0], {'role': 'system', 'content': REASONING_PROTOCOL_INSTRUCTION})
            saved = json.loads(diagnostic_path(root, 'captain-text-probe-raw').read_text())
            self.assertEqual(saved['request']['messages'], sent['messages'])
            self.assertNotIn('must-not-save', json.dumps(saved))
