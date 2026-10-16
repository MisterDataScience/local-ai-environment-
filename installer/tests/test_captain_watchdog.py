"""Freeze detection, restart ownership and real private-group termination."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import common
import managed_captain as managed
import runtime
import work_agent

MODE = {'mode': 'normal', 'transitioning': False, 'error': None}


class WatchdogTests(unittest.TestCase):
    def test_blocking_remote_work_is_not_mistaken_for_sleep(self):
        self.assertFalse(managed.resumed_from_sleep(100, 1000, 280, 1180))
        self.assertTrue(managed.resumed_from_sleep(100, 1000, 102, 4602))

    def process(self):
        process = Mock()
        process.poll.return_value = None
        return process

    def test_startup_grace_interval_and_three_consecutive_failures(self):
        watcher = managed.CaptainWatchdog()
        process = self.process()
        with patch.object(managed, 'agent_status', side_effect=TimeoutError()) as probe:
            for now in (0, 59):
                self.assertFalse(watcher.check('/root', process, MODE, now=now))
            probe.assert_not_called()
            self.assertFalse(watcher.check('/root', process, MODE, now=60))
            self.assertFalse(watcher.check('/root', process, MODE, now=89))
            self.assertFalse(watcher.check('/root', process, MODE, now=90))
            self.assertTrue(watcher.check('/root', process, MODE, now=120))
            self.assertEqual(probe.call_count, 3)
            self.assertEqual(probe.call_args.kwargs['timeout'], 3)

    def test_success_resets_failures_including_during_long_running_work(self):
        watcher = managed.CaptainWatchdog(grace=0)
        process = self.process()
        with patch.object(managed, 'agent_status', side_effect=[TimeoutError(), {}, TimeoutError(), {}]):
            for now in (0, 30, 60, 90):
                self.assertFalse(watcher.check('/root', process, MODE, now=now))
        self.assertEqual(watcher.failures, 0)
        # No inference/session status, output progress, tool approvals or wall
        # clock task duration is consulted when the control API is responsive.

    def test_wake_replacement_and_disabled_modes_reset_failure_streak(self):
        for mode in (None, {'mode': 'gaming', 'transitioning': False, 'error': None},
                     dict(MODE, transitioning=True), dict(MODE, error='gateway offline'), {}):
            with self.subTest(mode=mode), patch.object(managed, 'agent_status', side_effect=TimeoutError()) as probe:
                watcher = managed.CaptainWatchdog(grace=0)
                process = self.process()
                watcher.check('/root', process, MODE, now=0)
                watcher.check('/root', process, mode, now=30)
                self.assertEqual(watcher.failures, 0)
                self.assertEqual(probe.call_count, 1)
        watcher = managed.CaptainWatchdog()
        process = self.process()
        with patch.object(managed, 'agent_status', side_effect=TimeoutError()) as probe:
            watcher.check('/root', process, MODE, now=0)
            watcher.check('/root', process, MODE, now=60)
            self.assertFalse(watcher.check('/root', process, MODE, now=100, resumed=True))
            self.assertFalse(watcher.check('/root', process, MODE, now=159))
            self.assertEqual(watcher.failures, 0)
            self.assertFalse(watcher.check('/root', self.process(), MODE, now=160))
            self.assertEqual(probe.call_count, 1)

    def test_absent_or_exited_process_is_not_probed(self):
        exited = self.process(); exited.poll.return_value = 1
        with patch.object(managed, 'agent_status') as probe:
            for process in (None, exited):
                self.assertFalse(managed.CaptainWatchdog(grace=0).check('/root', process, MODE, now=0))
        probe.assert_not_called()

    def test_supervisor_retires_only_captain_then_preserves_other_service_records(self):
        captain, gateway = self.process(), self.process()
        processes = [('gateway', gateway), ('captain', captain)]
        watcher = Mock(); watcher.check.side_effect = [True, False]
        with patch.object(runtime, 'stop_process') as stop, patch('service_lifecycle.record') as record:
            self.assertTrue(runtime.check_captain_watchdog(Path('/installation'), processes, watcher,
                                                        MODE, now=120))
        stop.assert_called_once_with(captain, timeout=30)
        self.assertEqual(processes, [('gateway', gateway)])
        record.assert_called_once_with(Path('/installation'), processes)
        self.assertIsNone(watcher.check.call_args.args[1])

    def test_responsive_or_unowned_listener_does_not_authorize_stop(self):
        watcher = managed.CaptainWatchdog(grace=0)
        with patch.object(managed, 'agent_status', return_value={}), patch.object(runtime, 'stop_process') as stop:
            self.assertFalse(runtime.check_captain_watchdog(Path('/installation'), [], watcher, MODE, now=0))
        stop.assert_not_called()

    def test_managed_native_inherits_only_a_private_wrapper_group(self):
        with patch.object(work_agent.os, 'getpid', return_value=123), \
             patch.object(work_agent.os, 'getpgrp', return_value=123), \
             patch.object(work_agent.subprocess, 'Popen') as launch:
            work_agent.launch_native(['opencode', 'web'], '/project', {}, managed=True)
        self.assertFalse(launch.call_args.kwargs['start_new_session'])
        with patch.object(work_agent.os, 'getpid', return_value=123), \
             patch.object(work_agent.os, 'getpgrp', return_value=456), \
             patch.object(work_agent.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'own supervisor-owned process group'):
                work_agent.launch_native(['opencode'], '/project', {}, managed=True)
        launch.assert_not_called()
        with patch.object(common.os, 'killpg') as kill:
            with self.assertRaises(ValueError):
                common.stop_process(self.process(), group_id=os.getpgrp() + 100000)
        kill.assert_not_called()

    def test_real_authenticated_http_timeout_reaches_restart_threshold(self):
        release = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                if self.path != '/agent' or self.headers.get('Authorization') != self.server.auth:
                    self.send_error(401); return
                if self.server.hang:
                    release.wait(3)
                data = b'[{"name":"plan"},{"name":"build"}]'
                try:
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers(); self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'control').mkdir()
            auth = managed.credentials(root)
            server.auth = 'Basic ' + base64.b64encode((auth['username'] + ':' + auth['password']).encode()).decode()
            server.hang = False
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            process = self.process()
            watcher = managed.CaptainWatchdog(interval=1, grace=0, timeout=0.05)
            try:
                with patch.object(managed, 'URL', f'http://127.0.0.1:{server.server_port}'):
                    self.assertFalse(watcher.check(root, process, MODE, now=0))
                    server.hang = True
                    self.assertFalse(watcher.check(root, process, MODE, now=1))
                    self.assertFalse(watcher.check(root, process, MODE, now=2))
                    self.assertTrue(watcher.check(root, process, MODE, now=3))
            finally:
                release.set(); server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_real_frozen_wrapper_and_child_are_killed_as_one_private_group(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'heartbeat'
            child = "import signal,time,pathlib,sys; signal.signal(signal.SIGTERM,signal.SIG_IGN); p=pathlib.Path(sys.argv[1]);\nwhile True: p.write_text(str(time.monotonic_ns())); time.sleep(0.01)"
            wrapper = ("import signal,subprocess,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                       "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);\nwhile True: time.sleep(1)")
            process = subprocess.Popen([sys.executable, '-c', wrapper, child, str(marker)],
                                       start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists(), 'Synthetic native child did not start')
                common.stop_process(process, timeout=0.1)
                self.assertEqual(process.returncode, -signal.SIGKILL)
                stamp = marker.read_text()
                time.sleep(0.05)
                self.assertEqual(marker.read_text(), stamp, 'Native child survived wrapper recovery')
            finally:
                if process.poll() is None:
                    common.stop_process(process, timeout=0.1)


if __name__ == '__main__':
    unittest.main()
