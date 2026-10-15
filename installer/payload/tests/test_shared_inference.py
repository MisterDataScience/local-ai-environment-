import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from captain_config import upgrade, settings
from inference_scheduler import ModelQueue
from model_engine import Engine
from model_team import upgrade_team
from text_models import upgrade_text_configuration


def config():
    return upgrade(upgrade_team(upgrade_text_configuration({'text_model': 'qwen3:14b',
        'comfy_url': 'http://127.0.0.1:8189', 'ollama_url': 'http://127.0.0.1:11435'})))


class SharedInferenceTests(unittest.TestCase):
    def test_shared_native_requests_enter_backend_together_without_unloading_a_sibling(self):
        cfg = config()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'resource-mode.json').write_text('{"mode":"normal"}')
            engine = Engine(cfg, root)
            entered = threading.Barrier(3)
            release = threading.Event()
            active = 0
            maximum = 0
            lock = threading.Lock()
            def api(base, path, payload=None, **kwargs):
                nonlocal active, maximum
                if path == '/api/ps':
                    return {'models': []}
                if path == '/api/chat':
                    self.assertEqual(base, 'http://127.0.0.1:11436')
                    with lock:
                        active += 1; maximum = max(maximum, active)
                    entered.wait(3)
                    self.assertTrue(release.wait(3))
                    with lock:
                        active -= 1
                    return {'message': {'role': 'assistant', 'content': 'verified'},
                            'prompt_eval_count': 10, 'eval_count': 2}
                self.fail('Unexpected backend operation: ' + path)
            with patch('model_engine.api', side_effect=api), patch('model_engine.port_open', return_value=False):
                def request():
                    return {'model': cfg['captain']['model_id'], 'messages': [{'role': 'user', 'content': 'Independent task'}]}
                first, second = engine.submit(request()), engine.submit(request())
                try:
                    entered.wait(3)
                    self.assertEqual(engine.mode_status()['inference']['active'], 2)
                finally:
                    release.set()
                self.assertEqual(first.result(3), 'verified')
                self.assertEqual(second.result(3), 'verified')
                self.assertEqual(maximum, 2)
            engine.executor.shutdown()

    def test_exclusive_barrier_waits_for_all_readers_and_blocks_later_readers(self):
        scheduler = ModelQueue()
        first_started, release = threading.Event(), threading.Event()
        writer_started, release_writer = threading.Event(), threading.Event()
        order = []
        def first():
            with scheduler.lease('model', 2):
                order.append('first'); first_started.set(); release.wait(3)
        def writer():
            with scheduler.lease():
                order.append('media'); writer_started.set(); release_writer.wait(3)
        def later():
            with scheduler.lease('model', 2):
                order.append('later')
        with concurrent.futures.ThreadPoolExecutor(3) as executor:
            a = executor.submit(first); self.assertTrue(first_started.wait(3))
            b = executor.submit(writer)
            with scheduler.condition:
                self.assertTrue(scheduler.condition.wait_for(lambda: bool(scheduler.waiters), timeout=3))
            c = executor.submit(later)
            self.assertFalse(writer_started.is_set())
            release.set(); self.assertTrue(writer_started.wait(3)); release_writer.set()
            for future in (a, b, c): future.result(3)
        self.assertEqual(order, ['first', 'media', 'later'])

    def test_mode_change_invalidates_queued_shared_tasks_before_they_run(self):
        cfg = config()
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(cfg, Path(folder))
            engine.captain['max_parallel'] = 1
            started, release = threading.Event(), threading.Event()
            ran = []
            def run(messages, route, prompt, body):
                ran.append(prompt); started.set(); release.wait(3); return prompt
            request = lambda prompt: {'model': cfg['captain']['model_id'], 'messages': [{'role': 'user', 'content': prompt}]}
            with patch.object(engine, 'run', side_effect=run), patch.object(engine, 'unload_ollama'), patch('model_engine.port_open', return_value=False):
                first = engine.submit(request('first')); self.assertTrue(started.wait(3))
                queued = engine.submit(request('stale'))
                engine.change_mode('gaming'); release.set()
                self.assertEqual(first.result(3), 'first')
                with self.assertRaisesRegex(RuntimeError, 'mode changed'):
                    queued.result(3)
                engine.executor.shutdown()
            self.assertEqual(ran, ['first'])

    def test_configuration_preserves_an_explicit_disabled_captain_and_rejects_oversized_contexts(self):
        cfg = config(); cfg['captain']['enabled'] = False
        self.assertFalse(upgrade(cfg)['captain']['enabled'])
        cfg['captain']['enabled'] = True
        cfg['text_models']['local-ai-captain']['num_ctx'] = 32768
        with self.assertRaisesRegex(ValueError, '16K'):
            settings(cfg)

    def test_idle_model_release_never_interrupts_an_active_worker(self):
        cfg = config()
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(cfg, Path(folder))
            engine.shared_llama = Mock(process=object())
            engine.shared_last_used = -engine.text_models[cfg['captain']['model_id']]['keep_alive_seconds'] - 1
            with engine.model_jobs.lease('captain', 5):
                engine.expire_shared()
                engine.shared_llama.stop.assert_not_called()
            engine.expire_shared()
            engine.shared_llama.stop.assert_called_once()
            self.assertIsNone(engine.text_profile)
            engine.executor.shutdown()

    def test_mode_change_during_cold_gguf_start_prevents_stale_inference(self):
        cfg = config()
        cfg['captain'].update(provider='llama', single_model=True)
        cfg['text_models']['local-ai-captain'].update(backend='llama')
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(cfg, Path(folder))
            self.addCleanup(engine.executor.shutdown)
            engine.shared_llama = Mock()
            engine.shared_llama.start.side_effect = lambda *_, **__: engine.change_mode('gaming')
            body = {'model': 'local-ai-captain', 'messages': [{'role': 'user', 'content': 'A stale request'}]}
            with patch.object(engine, 'unload_ollama'), patch('model_engine.port_open', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'Mode switch'):
                    engine.submit(body).result(3)
                engine.executor.shutdown()
            engine.shared_llama.chat.assert_not_called()

    def test_backend_mismatches_and_disabled_native_presets_fail_closed(self):
        cfg = config()
        cfg['captain']['provider'] = 'llama'
        with self.assertRaisesRegex(ValueError, 'must match'):
            settings(cfg)
        cfg['text_models']['local-ai-captain']['backend'] = 'llama'
        settings(cfg)
        cfg['captain']['enabled'] = False
        from text_models import configured_text_models
        with self.assertRaisesRegex(ValueError, 'unconfigured text backend'):
            configured_text_models(cfg)


if __name__ == '__main__':
    unittest.main()
