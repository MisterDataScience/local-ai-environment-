"""Shared GGUF backend capacity and diagnostic regression coverage."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from shared_llama import SharedLlama


class NativeSlotTests(unittest.TestCase):
    def instance(self, log=None):
        return SharedLlama({'max_parallel': 5}, log_path=log)

    def test_context_pool_scales_with_active_mode_not_maximum_worker_count(self):
        shared = self.instance()
        with patch.object(shared, 'files', return_value={'binary': '/fixture/llama-server',
                                                         'model': '/fixture/model.gguf',
                                                         'mmproj': '/fixture/mmproj.gguf'}):
            normal = shared.command(16384, parallel=2)
            max_mode = shared.command(16384, parallel=5)
        self.assertEqual(normal[normal.index('--parallel') + 1], '2')
        self.assertEqual(normal[normal.index('--ctx-size') + 1], '32768')
        self.assertEqual(max_mode[max_mode.index('--ctx-size') + 1], '81920')
        self.assertEqual(max_mode[max_mode.index('--parallel') + 1], '5')

    def test_invalid_slots_cannot_exceed_configured_parallelism(self):
        shared = self.instance()
        for count in (0, 6, -1, True, '2'):
            with self.subTest(value=count):
                with self.assertRaisesRegex(ValueError, 'slots'):
                    shared.command(8192, parallel=count)

    def test_backend_startup_failure_preserves_private_log_file(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'logs/shared-llama.log'
            shared = self.instance(log)
            process = Mock()
            process.poll.return_value = 127
            with patch.object(shared, 'files', return_value={'binary': '/fixture/llama-server',
                                                             'model': '/fixture/model.gguf'}), \
                 patch('shared_llama.port_open', return_value=False), \
                 patch('shared_llama.subprocess.Popen', return_value=process) as launch:
                with self.assertRaisesRegex(RuntimeError, 'shared-llama.log'):
                    shared.start(8192, parallel=2)
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            self.assertEqual(launch.call_args.args[0][launch.call_args.args[0].index('--parallel') + 1], '2')
            self.assertEqual(shared.running_slots, 2)

    def test_running_server_refuses_capacity_change_without_mode_transition(self):
        shared = self.instance()
        shared.process = Mock()
        shared.process.poll.return_value = None
        shared.running_slots = 2
        shared.start(8192, parallel=2)
        with self.assertRaisesRegex(RuntimeError, 'slot count'):
            shared.start(8192, parallel=5)


if __name__ == '__main__':
    unittest.main()
