"""Recovery boundaries with failed Docker/Tailscale and a wedged gateway."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import runtime
import remote_access
import power_guard


class RecoveryTests(unittest.TestCase):
    def test_terminated_idle_guard_is_reacquired_and_healthy_one_reused(self):
        healthy = unittest.mock.Mock()
        healthy.poll.return_value = None
        dead = unittest.mock.Mock()
        dead.poll.return_value = 1
        with patch.object(power_guard, 'begin', return_value=healthy) as begin:
            self.assertIs(power_guard.maintain(dead), healthy)
            self.assertIs(power_guard.maintain(healthy), healthy)
        self.assertEqual(begin.call_count, 1)

    def test_docker_is_reopened_before_vpn_restart(self):
        events = []
        with patch('web_access.status', side_effect=OSError('Docker closed')), \
             patch('docker_setup.start_installed_docker', side_effect=lambda **kw: events.append('docker')), \
             patch('web_access.start', side_effect=lambda root: events.append('vpn')):
            runtime.recover_web(Path('/installation'))
        self.assertEqual(events, ['docker', 'vpn'])

    def test_healthy_vpn_does_not_reopen_docker(self):
        with patch('web_access.status', return_value={'status': 'ready'}), \
             patch('docker_setup.start_installed_docker') as docker:
            runtime.recover_web(Path('/installation'))
        docker.assert_not_called()

    def test_failed_docker_does_not_attempt_vpn_or_direct_fallback(self):
        with patch('web_access.status', side_effect=OSError()), \
             patch('docker_setup.start_installed_docker', side_effect=RuntimeError('offline')), \
             patch('web_access.start') as start:
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                runtime.recover_web(Path('/installation'))
        start.assert_not_called()

    def test_stopped_tailscale_is_reopened_before_route_reconciliation(self):
        app = unittest.mock.Mock()
        app.is_dir.return_value = True
        app.is_symlink.return_value = False
        events = []
        for status in ({'BackendState': 'Stopped'}, OSError('app quit')):
            with self.subTest(status=status), \
                 patch.object(remote_access, 'APP', app), \
                 patch.object(remote_access, 'cli_json', **(
                     {'side_effect': status} if isinstance(status, Exception) else {'return_value': status})), \
                 patch.object(runtime.subprocess, 'run', side_effect=lambda *a, **k: events.append('open')), \
                 patch.object(remote_access, 'reconcile_private_routes', side_effect=lambda r: events.append('routes')):
                runtime.recover_remote({'enabled': True})
        self.assertEqual(events, ['open', 'routes', 'open', 'routes'])

    def test_healthy_tailnet_is_not_reopened(self):
        with patch.object(remote_access, 'cli_json', return_value={'BackendState': 'Running'}), \
             patch.object(runtime.subprocess, 'run') as opened, \
             patch.object(remote_access, 'reconcile_private_routes', return_value=[]):
            self.assertEqual(runtime.recover_remote({'enabled': True}), [])
        opened.assert_not_called()

    def test_gateway_hang_is_part_of_core_health(self):
        def response(url, **kw):
            if url.endswith(':8001/health'):
                raise TimeoutError('gateway wedged')
            return {'status': True}
        with patch.object(runtime, 'http', side_effect=response):
            with self.assertRaisesRegex(TimeoutError, 'gateway wedged'):
                runtime.check_core_health()

    def test_ambiguous_route_timeout_rolls_back_only_attempted_missing_port(self):
        host = 'mac.example.ts.net'
        before = {'Web': {host + ':443': {'Handlers': {'/': {'Proxy': remote_access.TARGETS[443]}}}}}
        def execute(command, **kw):
            if command[-1] != 'off':
                raise subprocess.TimeoutExpired(command, 60)
        with patch.object(remote_access, 'cli_json', side_effect=[
                {'BackendState': 'Running', 'Self': {'DNSName': host}}, before]), \
             patch.object(remote_access, 'execute', side_effect=execute) as calls:
            with self.assertRaises(subprocess.TimeoutExpired):
                remote_access.reconcile_private_routes({'enabled': True, 'hostname': host})
        commands = [c.args[0] for c in calls.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertIn('--https=8443', commands[1])
        self.assertEqual(commands[1][-1], 'off')


if __name__ == '__main__':
    unittest.main()
