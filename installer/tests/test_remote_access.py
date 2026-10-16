import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote_access as remote

HOST = "mac-mini.example.ts.net"


def serve_config():
    return {"TCP": {str(port): {"HTTPS": True} for port in remote.TARGETS},
            "Web": {f"{HOST}:{port}": {"Handlers": {"/": {"Proxy": target}}}
                    for port, target in remote.TARGETS.items()}}


class RemoteAccessTests(unittest.TestCase):
    def test_hostname_requires_connected_tailnet(self):
        self.assertEqual(remote.connected_hostname({"BackendState": "Running", "Self": {"DNSName": HOST + "."}}), HOST)
        for status in ({"BackendState": "NeedsLogin"},
                       {"BackendState": "Running", "Self": {"DNSName": "https://evil.test"}}):
            with self.assertRaises(RuntimeError):
                remote.connected_hostname(status)

    def test_conflicting_or_public_routes_are_rejected(self):
        for config in ({"TCP": {"443": {"TCPForward": "127.0.0.1:22"}}},
                       {"Web": {HOST + ":443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9999"}}}}},
                       {"AllowFunnel": {HOST + ":443": True}}):
            with self.assertRaises(RuntimeError):
                remote.check_conflicts(config, HOST)
        remote.check_conflicts(serve_config(), HOST)

    def test_setup_preserves_settings_and_only_configures_private_proxies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control").mkdir()
            original = {"api_key": "existing-secret", "captain": {"enabled": True}, "text_models": {"unchanged": {"custom": 1}}}
            path = root / "control/config.json"
            path.write_text(json.dumps(original))
            with patch.object(remote, "install_client"), patch.object(remote, "wait_for_connection", return_value=HOST), \
                 patch("managed_captain.credentials", return_value={'username': 'opencode', 'password': 'x'*48}), \
                 patch.object(remote, "cli_json", side_effect=[{}, serve_config()]), \
                 patch.object(remote, "execute") as execute:
                result = remote.configure(root)
            config = json.loads(path.read_text())
            self.assertEqual(config["api_key"], original["api_key"])
            self.assertEqual(config["text_models"], original["text_models"])
            self.assertEqual(result["media_url"], f"https://{HOST}:8443")
            self.assertEqual(result["captain_url"], f"https://{HOST}:10000")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((root / "control/config.before-remote-access.json").read_text()), original)
            commands = [call.args[0] for call in execute.call_args_list]
            self.assertEqual(len(commands), 3)
            self.assertTrue(all(command[1:4] == ["serve", "--bg", "--yes"] for command in commands))
            self.assertEqual(commands[0][-1], "http://127.0.0.1:8081")
            self.assertEqual(commands[1][-1], "http://127.0.0.1:8002")
            self.assertEqual(commands[2][-1], "http://127.0.0.1:4096")
            self.assertNotIn("funnel", str(commands))
            self.assertNotIn("exit-node", str(commands))

    def test_setup_conflict_does_not_mutate_routes_or_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control").mkdir()
            path = root / "control/config.json"
            path.write_text('{"api_key": "keep", "captain": {"enabled": true}}')
            before = path.read_bytes()
            with patch.object(remote, "install_client"), patch.object(remote, "wait_for_connection", return_value=HOST), \
                 patch("managed_captain.credentials", return_value={'username': 'opencode', 'password': 'x'*48}), \
                 patch.object(remote, "cli_json", return_value={"AllowFunnel": {HOST + ":443": True}}), \
                 patch.object(remote, "execute") as execute:
                with self.assertRaises(RuntimeError):
                    remote.configure(root)
            execute.assert_not_called()
            self.assertEqual(path.read_bytes(), before)

    def test_partial_setup_rolls_back_only_new_ports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control").mkdir()
            path = root / "control/config.json"
            path.write_text('{"captain":{"enabled":true}}')
            before = {"TCP": {"443": {"HTTPS": True}},
                      "Web": {HOST + ":443": {"Handlers": {"/": {"Proxy": remote.TARGETS[443]}}}}}
            def execute(command, **kwargs):
                if command[-1] != "off" and "--https=8443" in command:
                    raise RuntimeError("setup failed")
            with patch.object(remote, "install_client"), patch.object(remote, "wait_for_connection", return_value=HOST), \
                 patch("managed_captain.credentials", return_value={'username': 'opencode', 'password': 'x'*48}), \
                 patch.object(remote, "cli_json", return_value=before), \
                 patch.object(remote, "execute", side_effect=execute) as calls:
                with self.assertRaises(RuntimeError):
                    remote.configure(root)
            off = [c.args[0] for c in calls.call_args_list if c.args[0][-1] == "off"]
            self.assertEqual(len(off), 1)
            self.assertIn("--https=8443", off[0])
            self.assertEqual(path.read_text(), '{"captain":{"enabled":true}}')

    def test_disable_does_not_reset_or_uninstall_tailscale(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control").mkdir()
            path = root / "control/config.json"
            path.write_text(json.dumps({"remote_access": {"enabled": True, "hostname": HOST}}))
            with patch.object(remote, "cli_json", return_value=serve_config()), patch.object(remote, "execute") as execute:
                remote.disable(root)
            commands = [call.args[0] for call in execute.call_args_list]
            self.assertEqual(len(commands), 3)
            self.assertTrue(all(command[-1] == "off" for command in commands))
            self.assertNotIn("reset", str(commands))
            self.assertFalse(json.loads(path.read_text())["remote_access"]["enabled"])

    def test_reconnect_restores_only_missing_captain_https_route(self):
        connected = {'BackendState': 'Running', 'Self': {'DNSName': HOST}}
        before = serve_config()
        before['Web'].pop(HOST + ':10000')
        before['TCP'].pop('10000')
        with patch.object(remote, 'cli_json', side_effect=[connected, before, serve_config()]), \
             patch.object(remote, 'execute') as execute:
            changed = remote.reconcile_private_routes({'enabled': True, 'hostname': HOST})
        self.assertEqual(changed, [10000])
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0][-1], 'http://127.0.0.1:4096')
        self.assertIn('--https=10000', execute.call_args.args[0])

    def test_reconnect_noops_for_healthy_routes(self):
        connected = {'BackendState': 'Running', 'Self': {'DNSName': HOST}}
        with patch.object(remote, 'cli_json', side_effect=[connected, serve_config()]), \
             patch.object(remote, 'execute') as execute:
            self.assertEqual(remote.reconcile_private_routes({'enabled': True, 'hostname': HOST}), [])
        execute.assert_not_called()

    def test_reconnect_never_steals_another_route_or_enables_public_funnel(self):
        connected = {'BackendState': 'Running', 'Self': {'DNSName': HOST}}
        conflict = serve_config()
        conflict['Web'][HOST + ':10000']['Handlers']['/']['Proxy'] = 'http://127.0.0.1:9999'
        public = serve_config()
        public['AllowFunnel'] = {HOST + ':10000': True}
        for unsafe in (conflict, public):
            with self.subTest(config=unsafe), \
                 patch.object(remote, 'cli_json', side_effect=[connected, unsafe]), \
                 patch.object(remote, 'execute') as execute:
                with self.assertRaises(RuntimeError):
                    remote.reconcile_private_routes({'enabled': True, 'hostname': HOST})
                execute.assert_not_called()

    def test_reconnect_rollback_preserves_existing_private_routes(self):
        connected = {'BackendState': 'Running', 'Self': {'DNSName': HOST}}
        before = serve_config()
        before['Web'].pop(HOST + ':10000')
        before['TCP'].pop('10000')
        def action(command, **kwargs):
            if command[-1] != 'off':
                return None
        with patch.object(remote, 'cli_json', side_effect=[connected, before, before]), \
             patch.object(remote, 'execute', side_effect=action) as execute:
            with self.assertRaisesRegex(RuntimeError, 'did not restore'):
                remote.reconcile_private_routes({'enabled': True, 'hostname': HOST})
        off = [call.args[0] for call in execute.call_args_list if call.args[0][-1] == 'off']
        self.assertEqual(len(off), 1)
        self.assertIn('--https=10000', off[0])

    def test_untrusted_package_is_not_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cache").mkdir()
            (root / "cache" / f"Tailscale-{remote.TAILSCALE_VERSION}-macos.pkg").write_bytes(b"fake")
            with patch.object(remote, "APP", root / "missing.app"), \
                 patch.object(remote, "CLI", root / "missing-cli"), \
                 patch.object(remote, "execute", return_value="Untrusted publisher") as execute:
                with self.assertRaises(RuntimeError):
                    remote.install_client(root)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.args[0][0], "/usr/sbin/pkgutil")

    def test_cli_runs_without_shell_and_forces_cli_mode(self):
        with patch.object(remote.subprocess, "run", return_value=Mock(stdout="{}")) as run:
            remote.execute([remote.CLI, "status", "--json"], capture=True)
            self.assertEqual(run.call_args.kwargs["env"]["TAILSCALE_BE_CLI"], "1")
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(run.call_args.args[0][-2:], ["status", "--json"])

    def test_connection_wait_times_out_without_storing_credentials(self):
        with patch.object(remote.time, "monotonic", side_effect=[0, 0, 0, 0, 2]), \
             patch.object(remote.time, "sleep"), patch.object(remote, "cli_json", return_value={"BackendState": "NeedsLogin"}):
            with self.assertRaises(RuntimeError):
                remote.wait_for_connection(timeout=1)

    def test_private_captain_requires_two_real_authentication_outcomes(self):
        settings = {'hostname': HOST, 'captain_url': f'https://{HOST}:10000'}
        unauthorized = HTTPError(settings['captain_url'] + '/agent', 401, 'Authentication required', {}, None)
        client = Mock()
        client.open.side_effect = [unauthorized, io.BytesIO(
            b'[{"name":"plan"},{"name":"build"}]'),
            HTTPError(settings['captain_url'] + '/', 401, 'unauthorised', {}, None),
            io.BytesIO(b'<!doctype html><html><body>Captain</body></html>')]
        with (patch.object(remote, 'build_opener', return_value=client),
              patch('managed_captain.agent_status', return_value={'captain_agent_endpoint': 'passed'}),
              patch('managed_captain.credentials', return_value={
                 'username': 'opencode', 'password': 'not-a-real-private-password'})):
            checked = remote.verify_captain_access(Path('/tmp'), settings)
        self.assertEqual(checked['status'], 'passed')
        self.assertTrue(checked['login_required'])
        self.assertEqual(checked['html_ui'], 'passed')
        self.assertEqual(checked['browser_approvals'], 'pending')
        first = client.open.call_args_list[0].args[0]
        second = client.open.call_args_list[1].args[0]
        self.assertNotIn('Authorization', first.headers)
        self.assertIn('Authorization', second.headers)
        self.assertEqual(first.full_url, second.full_url)

    def test_remote_captain_refuses_public_or_unexpected_endpoint_and_redirects(self):
        settings = {'hostname': HOST, 'captain_url': 'https://public.example.com'}
        with patch('managed_captain.agent_status') as check:
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                remote.verify_captain_access(Path('/tmp'), settings)
            check.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'redirected'):
            remote.NoCrossOriginRedirect().redirect_request(None, None, 302, 'moved', {},
                                                             'https://evil.example/')

    def test_https_acceptance_checks_media_isolation_and_removes_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control/media").mkdir(parents=True)
            settings = {"enabled": True, "hostname": HOST, "ui_url": f"https://{HOST}",
                        "media_url": f"https://{HOST}:8443",
                        "captain_url": f"https://{HOST}:10000"}
            requested = []
            def open_url(url, timeout=30):
                requested.append(url)
                if url == settings["ui_url"] + "/health":
                    return io.BytesIO(b'{"status": true}')
                if url.startswith(settings["media_url"] + "/media/remote-check-"):
                    name = url.rsplit("/", 1)[-1]
                    return io.BytesIO((root / "control/media" / name).read_bytes())
                raise HTTPError(url, 404, "not found", {}, None)
            with patch.object(remote, "cli_json", side_effect=[
                    {"BackendState": "Running", "Self": {"DNSName": HOST}}, serve_config()]), \
                 patch.object(remote, "urlopen", side_effect=open_url), \
                 patch.object(remote, "verify_captain_access", return_value={"status": "passed"}):
                remote.verify_remote_access(root, settings)
            report = json.loads((root / "remote-acceptance-report.json").read_text())
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["other_device_browser_test"], "pending")
            self.assertEqual(report['captain_authentication']['status'], 'passed')
            self.assertIn(settings["media_url"] + "/v1/models", requested)
            self.assertEqual(list((root / "control/media").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
