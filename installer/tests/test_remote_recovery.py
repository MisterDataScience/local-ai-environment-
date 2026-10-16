"""Nonblocking repair, process lifetime and fail-closed result propagation."""
from concurrent.futures import ThreadPoolExecutor
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

import remote_access
import remote_recovery as recovery
import runtime

REMOTE = {'enabled': True, 'hostname': 'mac.example.ts.net'}


class RecoveryWorkerTests(unittest.TestCase):
    def test_running_attempt_never_overlaps_and_completion_starts_cooldown(self):
        process = Mock(); process.poll.return_value = None
        worker = recovery.RemoteRecovery('/installation', REMOTE)
        with patch.object(recovery, 'launch', return_value=process) as launch:
            worker.tick(now=0)
            self.assertIn('--verify', launch.call_args.args[0])
            for now in (1, 120, 10000):
                worker.tick(now=now)
            self.assertEqual(launch.call_count, 1)
            process.poll.return_value = 0
            worker.tick(now=10001)
            worker.tick(now=10120)
            self.assertEqual(launch.call_count, 1)
            worker.tick(now=10121)
            self.assertEqual(launch.call_count, 2)
            self.assertNotIn('--verify', launch.call_args.args[0])

    def test_failed_attempt_requires_full_verification_on_retry(self):
        process = Mock(); process.poll.return_value = 1
        worker = recovery.RemoteRecovery('/installation', REMOTE)
        with patch.object(recovery, 'launch', return_value=process) as launch:
            worker.tick(now=0)
            worker.tick(now=1)
            worker.tick(now=121)
        self.assertEqual(launch.call_count, 2)
        self.assertIn('--verify', launch.call_args.args[0])

    def test_worker_does_not_inherit_provider_credentials_or_proxy_overrides(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-secret', 'HTTP_PROXY': 'http://proxy.invalid'}), \
             patch.object(recovery, 'launch') as launch:
            recovery.RemoteRecovery('/installation', REMOTE).tick(now=0)
        environment = launch.call_args.args[3]
        self.assertNotIn('OPENAI_API_KEY', environment)
        self.assertNotIn('HTTP_PROXY', environment)
        self.assertNotIn('LOCAL_AI_GATEWAY_KEY', environment)

    def test_funnel_failure_is_not_treated_as_a_transient_reconnect(self):
        process = Mock(); process.poll.return_value = recovery.FUNNEL_EXIT
        worker = recovery.RemoteRecovery('/installation', REMOTE)
        with patch.object(recovery, 'launch', return_value=process):
            worker.tick(now=0)
            with self.assertRaises(remote_access.PublicFunnelError):
                worker.tick(now=1)
        self.assertIsNone(worker.process)

    def test_disabled_closed_and_failed_start_do_not_launch_retry_storms(self):
        with patch.object(recovery, 'launch', side_effect=OSError()) as launch:
            recovery.RemoteRecovery('/installation', {'enabled': False}).tick(now=0)
            worker = recovery.RemoteRecovery('/installation', REMOTE)
            worker.tick(now=0)
            worker.tick(now=119)
            self.assertEqual(launch.call_count, 1)
            worker.close()
            worker.tick(now=1000)
            self.assertEqual(launch.call_count, 1)

    def test_close_stops_only_its_worker_once_and_prevents_new_work(self):
        process = Mock()
        worker = recovery.RemoteRecovery('/installation', REMOTE)
        with patch.object(recovery, 'launch', return_value=process), \
             patch.object(recovery, 'stop_process') as stop:
            worker.tick(now=0)
            worker.close()
            worker.close()
            worker.tick(now=1000)
        stop.assert_called_once_with(process, timeout=10)

    def test_hostname_change_refuses_route_mutations_and_repairs_verify(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'control').mkdir()
            (root / 'control/config.json').write_text(json.dumps({'remote_access': REMOTE}))
            with patch.object(recovery, 'recover_remote') as repair:
                with self.assertRaisesRegex(RuntimeError, 'settings changed'):
                    recovery.run(root, 'other.example.ts.net', True)
            repair.assert_not_called()
            for repaired, verify, expected in (([], False, False), ([], True, True), ([10000], False, True)):
                with self.subTest(repaired=repaired, verify=verify), \
                     patch.object(recovery, 'recover_remote', return_value=repaired), \
                     patch.object(remote_access, 'verify_remote_access') as check:
                    self.assertEqual(recovery.run(root, REMOTE['hostname'], verify), repaired)
                self.assertEqual(check.called, expected)

    def test_funnel_notification_requires_live_parent_relationship(self):
        with patch.object(recovery.os, 'getppid', return_value=123), \
             patch.object(recovery.os, 'kill') as kill:
            recovery.notify_funnel(456)
            kill.assert_not_called()
            recovery.notify_funnel(123)
            kill.assert_called_once_with(123, signal.SIGUSR1)
        self.assertFalse(issubclass(runtime.RemoteSecurityStop, Exception))
        with self.assertRaises(runtime.RemoteSecurityStop):
            runtime.stop_for_public_funnel(signal.SIGUSR1, None)

    def test_worker_main_keeps_funnel_distinct_from_ordinary_errors(self):
        for failure, expected in ((remote_access.PublicFunnelError(), recovery.FUNNEL_EXIT),
                                  (TimeoutError(), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(failure=type(failure).__name__), \
                 patch.object(sys, 'argv', ['remote_recovery', '--root', '/installation',
                     '--hostname', REMOTE['hostname'], '--supervisor-pid', '99']), \
                 patch.object(recovery.os, 'getpid', return_value=100), \
                 patch.object(recovery.os, 'getpgrp', return_value=100), \
                 patch.object(recovery.os, 'getppid', return_value=99), \
                 patch.object(recovery.signal, 'signal'), \
                 patch.object(recovery.threading, 'Thread'), \
                 patch.object(recovery, 'run', side_effect=failure), \
                 patch.object(recovery, 'failed_report'), \
                 patch.object(recovery, 'notify_funnel') as notify:
                self.assertEqual(recovery.main(), expected)
            self.assertEqual(notify.called, expected == recovery.FUNNEL_EXIT)

    def test_orphan_worker_cancels_its_private_group(self):
        done = Mock(); done.wait.return_value = False
        with patch.object(recovery.os, 'getppid', return_value=1), \
             patch.object(recovery.os, 'getpid', return_value=123), \
             patch.object(recovery.os, 'killpg') as kill:
            recovery.monitor_parent(99, done)
        kill.assert_called_once_with(123, signal.SIGTERM)

    def test_real_funnel_signal_interrupts_a_supervisor_without_waiting_for_its_tick(self):
        child = 'import os; from remote_recovery import notify_funnel; notify_funnel(os.getppid())'
        parent = ('import signal,subprocess,sys,time; '
                  f'signal.signal(signal.SIGUSR1,lambda *_:sys.exit({recovery.FUNNEL_EXIT})); '
                  'subprocess.Popen([sys.executable,"-c",sys.argv[1]]); time.sleep(30)')
        process = subprocess.Popen([sys.executable, '-c', parent, child], start_new_session=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(process.wait(timeout=5), recovery.FUNNEL_EXIT)
        finally:
            if process.poll() is None:
                recovery.stop_process(process, timeout=0.1)

    def test_parallel_report_writers_have_private_atomic_temporary_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); report = root / 'report.json'
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda n: remote_access.atomic_json(report, {'writer': n}), range(32)))
            self.assertIn(json.loads(report.read_text())['writer'], range(32))
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(root.iterdir()), [report])

    def test_stalled_real_worker_does_not_block_health_monitoring_and_is_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'control/.venv/bin').mkdir(parents=True)
            (root / 'logs').mkdir()
            (root / 'control/.venv/bin/python').symlink_to(sys.executable)
            marker = root / 'started'
            (root / 'control/remote_recovery.py').write_text(
                'import signal,time,pathlib\n'
                'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                f'pathlib.Path({str(marker)!r}).write_text("started")\n'
                'time.sleep(60)\n')
            worker = recovery.RemoteRecovery(root, REMOTE)
            try:
                worker.tick(now=0)
                process = worker.process
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                with patch.object(runtime, 'http', return_value={}) as health:
                    for n in range(10):
                        worker.tick(now=1000 + n)
                        runtime.check_core_health()
                self.assertEqual(health.call_count, 30)
                self.assertIs(worker.process, process)
                self.assertIsNone(process.poll())
                worker.close(timeout=0.1)
                self.assertEqual(process.returncode, -signal.SIGKILL)
            finally:
                worker.close(timeout=0.1)


if __name__ == '__main__':
    unittest.main()
