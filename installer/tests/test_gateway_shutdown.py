"""Use real process groups to check one signal and hung-tree recovery."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import common
from shared_llama import SharedLlama


class GatewayShutdownTests(unittest.TestCase):
    def test_cooperative_gateway_sends_one_signal_to_its_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            child = """import signal,sys,time,pathlib
root=pathlib.Path(sys.argv[1]); count=0; deadline=None
def stop(sig,frame):
 global count,deadline
 count+=1; (root/'signals').write_text(str(count))
 if count>1: sys.exit(91)
 deadline=time.monotonic()+0.3
signal.signal(signal.SIGTERM,stop)
(root/'ready').write_text('yes')
while deadline is None or time.monotonic()<deadline: time.sleep(0.01)
"""
            (root / 'child.py').write_text(child)
            controller = """import signal,subprocess,sys,time,pathlib
from shared_llama import SharedLlama
import shared_llama
root=pathlib.Path(sys.argv[1]); backend=SharedLlama({})
shared_llama.port_open=lambda _: False
backend.process=subprocess.Popen([sys.executable,str(root/'child.py'),str(root)])
def stop(sig,frame):
 time.sleep(0.05); backend.stop(); (root/'clean').write_text('yes'); sys.exit(0)
signal.signal(signal.SIGTERM,stop)
while True: time.sleep(0.01)
"""
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'payload'))
            process = subprocess.Popen([sys.executable, '-c', controller, str(root)],
                env=env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not (root / 'ready').exists() and time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(process.communicate()[1].decode())
                    time.sleep(0.01)
                self.assertTrue((root / 'ready').exists())
                self.assertNotEqual(process.pid, os.getpid())
                self.assertEqual(os.getpgid(process.pid), process.pid)
                common.stop_process(process, timeout=5, cooperative=True)
                self.assertEqual((root / 'signals').read_text(), '1')
                self.assertEqual((root / 'clean').read_text(), 'yes')
                self.assertEqual(process.returncode, 0)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
                process.stderr.close()

    def test_cooperative_timeout_still_kills_the_whole_private_group(self):
        process = Mock(pid=123)
        process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 1), -signal.SIGKILL]
        with patch.object(common.os, 'killpg') as kill:
            common.stop_process(process, timeout=1, cooperative=True)
        process.terminate.assert_called_once()
        kill.assert_called_once_with(123, signal.SIGKILL)

    def test_abnormal_native_shutdown_is_not_silently_accepted(self):
        backend = SharedLlama({})
        backend.process = Mock()
        backend.process.poll.return_value = -signal.SIGABRT
        backend.process.wait.return_value = -signal.SIGABRT
        with patch('shared_llama.port_open', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'abnormally'):
                backend.stop()
