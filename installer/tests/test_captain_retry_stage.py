"""Real acceptance gates and service lifecycle; only native processes are stubbed."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
import acceptance_diagnostics as diagnostics
import captain_check
import feature_checks
import feature_install
import feature_state
import resource_modes


class CaptainRetryStageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.control = self.root / 'control'
        self.control.mkdir()
        (self.root / 'logs').mkdir()
        self.config = {'feature_schema': 1, 'api_key': 'test-only-key',
                       'captain': {'enabled': True, 'provider': 'llama'},
                       'text_models': {'local-ai-captain': {'model': 'MiniCPM', 'thinking': True}}}
        (self.control / 'config.json').write_text(json.dumps(self.config))
        feature_state.write(self.root, 'core', 'failed', last_failure='ReadinessError',
                            acceptance={'earlier_checks': 'preserved'}, current_stage='native-acceptance')
        self.receipt = feature_state.state_path(self.root, 'core')
        self.original = self.receipt.read_bytes()
        self.progress = self.root / 'acceptance-report.json'
        self.progress.write_text('{"checks":[{"name":"text","status":"passed"}]}')
        resource_modes.save(self.control, 'normal')
        self.events = []
        self.processes = []
        self.stack.enter_context(patch.object(feature_install, 'ensure_stopped'))
        self.stack.enter_context(patch.object(feature_checks, 'ollama_binary', return_value='/fixture/ollama'))
        self.stack.enter_context(patch.object(feature_checks, 'launch', side_effect=self.launch))
        self.stack.enter_context(patch.object(feature_checks, 'wait_ready'))
        self.stack.enter_context(patch.object(feature_checks, 'stop_process', side_effect=self.stop))
        self.verify = self.stack.enter_context(patch.object(captain_check, 'verify', side_effect=self.native))
        previous = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous))

    def launch(self, command, folder, log, env):
        self.assertEqual(feature_state.read(self.root, 'core')['status'], 'testing')
        self.assertEqual(resource_modes.load(self.control), 'max')
        kind = 'gateway' if str(command[-1]).endswith('gateway.py') else 'ollama'
        if kind == 'gateway':
            features = tuple(filter(None, env['LOCAL_AI_ACCEPTANCE_FEATURES'].split(',')))
            child_view = feature_state.effective_config(self.root, self.config, testing=features)
            self.assertEqual(child_view['_feature_status']['core'], 'ready')
        ordinary_view = feature_state.effective_config(self.root, self.config)
        self.assertFalse(feature_state.available(ordinary_view, 'core'))
        self.events.append('start-' + kind)
        process = Mock(name=kind)
        self.processes.append(process)
        return process

    def stop(self, process, **kwargs):
        self.assertEqual(feature_state.read(self.root, 'core')['status'], 'testing')
        self.events.append('stop-' + ('gateway' if process is self.processes[-1] else 'ollama'))

    def native(self, root, config):
        self.assertEqual(root, self.root)
        self.assertEqual(config['_feature_status']['core'], 'ready')
        self.assertEqual(feature_state.read(root, 'core')['status'], 'testing')
        self.assertNotIn('_feature_status', json.loads((self.control / 'config.json').read_text()))
        self.events.append('captain-check')
        return [{'name': 'native-captain-team', 'status': 'passed'}]

    def restored(self):
        self.assertEqual(self.receipt.read_bytes(), self.original)
        self.assertEqual(resource_modes.load(self.control), 'normal')
        self.assertEqual(json.loads((self.control / 'config.json').read_text()), self.config)
        self.assertEqual(self.progress.read_text(), '{"checks":[{"name":"text","status":"passed"}]}')
        self.assertFalse((self.root / 'accepted-core-fingerprint.txt').exists())

    def test_failed_core_runs_only_captain_through_real_acceptance_gates(self):
        with self.assertRaisesRegex(RuntimeError, 'installer-owned acceptance stage'):
            feature_state.effective_config(self.root, self.config, testing=('core',))
        report = diagnostics.retry_captain(self.root)
        self.assertEqual(report['probe']['status'], 'passed', report['probe'])
        self.assertTrue(report['new_inference_requested'])
        self.assertEqual(self.events, ['start-ollama', 'start-gateway', 'captain-check', 'stop-gateway', 'stop-ollama'])
        self.verify.assert_called_once()
        self.assertEqual(report['core_feature_state']['status'], 'failed')
        self.assertFalse(report['full_installation_acceptance_performed'])
        self.restored()
        with self.assertRaisesRegex(RuntimeError, 'installer-owned acceptance stage'):
            feature_state.effective_config(self.root, self.config, testing=('core',))

    def test_configured_and_ready_receipts_are_restored_after_a_scoped_pass(self):
        for status in ('configured', 'testing', 'ready'):
            with self.subTest(status=status):
                feature_state.write(self.root, 'core', status)
                self.original = self.receipt.read_bytes()
                self.assertEqual(diagnostics.retry_captain(self.root)['probe']['status'], 'passed')
                self.restored()

    def test_native_failure_stops_owned_services_before_restoring_core(self):
        self.verify.side_effect = RuntimeError('Native dispatch failed')
        report = diagnostics.retry_captain(self.root)
        self.assertEqual(report['probe']['error'], 'Native dispatch failed')
        self.assertEqual(report['probe']['failure_stage'], 'captain_native_check')
        self.assertEqual(report['probe']['status'], 'failed')
        self.assertTrue(report['new_inference_requested'])
        self.assertEqual(self.events[-2:], ['stop-gateway', 'stop-ollama'])
        self.restored()

    def test_startup_failure_restores_state_without_claiming_model_inference(self):
        with patch.object(feature_checks, 'launch', side_effect=OSError('Could not launch Ollama')):
            report = diagnostics.retry_captain(self.root)
        self.assertEqual(report['probe']['failure_stage'], 'services_startup')
        self.assertFalse(report['new_inference_requested'])
        self.verify.assert_not_called()
        self.restored()

    def test_cleanup_error_preserves_the_native_error_and_restores_the_receipt(self):
        self.verify.side_effect = RuntimeError('Primary native failure')
        with patch.object(feature_checks, 'stop_process', side_effect=OSError('Cleanup failed')):
            report = diagnostics.retry_captain(self.root)
        self.assertEqual(report['probe']['error'], 'Primary native failure')
        self.assertEqual(report['probe']['cleanup_errors'], ['Cleanup failed'])
        self.restored()

    def test_invalid_receipt_stops_before_service_startup_and_is_preserved(self):
        self.receipt.write_text('{invalid owner state')
        report = diagnostics.retry_captain(self.root)
        self.assertEqual(report['probe']['status'], 'failed')
        self.assertEqual(report['probe']['failure_stage'], 'acceptance_state_setup')
        self.assertFalse(report['new_inference_requested'])
        self.assertEqual(self.receipt.read_text(), '{invalid owner state')
        self.assertEqual(self.events, [])
        self.verify.assert_not_called()

    def test_a_missing_receipt_is_removed_after_the_temporary_testing_stage(self):
        self.receipt.unlink()
        report = diagnostics.retry_captain(self.root)
        self.assertEqual(report['probe']['status'], 'passed')
        self.assertFalse(self.receipt.exists())

    def test_interrupt_restores_prior_state(self):
        with self.assertRaises(KeyboardInterrupt):
            with diagnostics._captain_acceptance_stage(self.root):
                self.assertEqual(feature_state.read(self.root, 'core')['status'], 'testing')
                raise KeyboardInterrupt
        self.restored()

    def test_a_concurrent_manual_receipt_change_is_preserved(self):
        with self.assertRaisesRegex(RuntimeError, 'Core receipt changed'):
            with diagnostics._captain_acceptance_stage(self.root):
                self.receipt.write_bytes(b'{"manual":"change"}')
        self.assertEqual(self.receipt.read_bytes(), b'{"manual":"change"}')


if __name__ == '__main__':
    unittest.main()
