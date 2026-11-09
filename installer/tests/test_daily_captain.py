"""Daily launcher routing and real HTTP sign-in checks, without native claims."""
import base64
from contextlib import ExitStack, redirect_stdout
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
from managed_captain import credentials, ui_status
from turnkey_install import open_captain


class UIProbeTests(unittest.TestCase):
    def probe(self, mode):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'control').mkdir()
            auth = credentials(root)
            expected = 'Basic ' + base64.b64encode((auth['username'] + ':' + auth['password']).encode()).decode()
            seen = []
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass
                def do_GET(self):
                    seen.append(self.path)
                    if mode == 'redirect':
                        self.send_response(302)
                        self.send_header('Location', '/elsewhere')
                    elif mode != 'public' and self.headers.get('Authorization') != expected:
                        self.send_response(401)
                        self.send_header('WWW-Authenticate', 'Basic realm="Captain"')
                    elif mode == 'reject':
                        self.send_response(401)
                    else:
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/html')
                        self.end_headers()
                        self.wfile.write(b'<html><script src="/app.js"></script></html>' if mode != 'broken' else b'not the app')
                        return
                    self.end_headers()
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with patch('managed_captain.URL', 'http://127.0.0.1:' + str(server.server_port)):
                    if mode == 'valid':
                        self.assertEqual(ui_status(root)['captain_sign_in'], 'passed')
                    else:
                        with self.assertRaises(RuntimeError):
                            ui_status(root)
                self.assertNotIn('/elsewhere', seen)
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def test_real_http_sign_in(self):
        self.probe('valid')

    def test_public_broken_rejected_and_redirected_pages_fail(self):
        for mode in ('public', 'broken', 'reject', 'redirect'):
            with self.subTest(mode=mode):
                self.probe(mode)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / 'control').mkdir()
        self.config = {'captain': {'enabled': True}, 'feature_schema': 1,
                       '_feature_status': {'core': 'ready'}}
        (self.root / 'control/config.json').write_text(json.dumps(self.config))
        self.accept = self.stack.enter_context(patch('turnkey_install.acceptance_summary'))
        self.stack.enter_context(patch('feature_state.effective_config', side_effect=lambda root, config: config))
        self.mode = self.stack.enter_context(patch('resource_modes.load', return_value='normal'))
        self.start = self.stack.enter_context(patch('turnkey_install.start_login_service'))
        self.launch = self.stack.enter_context(patch('turnkey_install.subprocess.run', return_value=Mock(returncode=0)))
        self.live = self.stack.enter_context(patch('turnkey_install.await_background'))
        self.open = self.stack.enter_context(patch('turnkey_install.open_local_ui'))
        self.output = io.StringIO()
        self.stack.enter_context(redirect_stdout(self.output))

    def test_stopped_install_starts_then_checks_then_opens(self):
        order = []
        self.start.side_effect = lambda root: order.append('start')
        self.live.side_effect = lambda *a, **k: order.append('check')
        self.open.side_effect = lambda root: order.append('open')
        self.assertEqual(open_captain(self.root), 0)
        self.assertEqual(order, ['start', 'check', 'open'])
        self.assertNotIn('-k', self.launch.call_args.args[0])

    def test_running_supervisor_is_not_restarted(self):
        with (self.root / '.runtime.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(open_captain(self.root), 0)
        self.start.assert_not_called()
        self.launch.assert_not_called()
        self.open.assert_called_once()

    def test_failed_acceptance_never_starts_or_opens(self):
        self.accept.side_effect = RuntimeError('Native acceptance incomplete: text-local-ai-team-document')
        self.assertEqual(open_captain(self.root), 1)
        self.start.assert_not_called()
        self.open.assert_not_called()
        self.assertIn('text-local-ai-team-document', self.output.getvalue())

    def test_failed_live_check_never_opens_browser(self):
        self.live.side_effect = RuntimeError('Captain chat page rejected its saved sign-in')
        self.assertEqual(open_captain(self.root), 1)
        self.open.assert_not_called()
        self.assertIn('live services and chat sign-in', self.output.getvalue())

    def test_gaming_mode_is_preserved(self):
        self.mode.return_value = 'gaming'
        self.assertEqual(open_captain(self.root), 1)
        self.start.assert_not_called()
        self.assertIn('AI Modes.command', self.output.getvalue())

    def test_second_click_does_not_launch_again(self):
        with (self.root / '.captain-open.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(open_captain(self.root), 0)
        self.start.assert_not_called()
        self.open.assert_not_called()

    def test_stale_core_receipt_fails(self):
        self.config['_feature_status']['core'] = 'configured'
        (self.root / 'control/config.json').write_text(json.dumps(self.config))
        self.assertEqual(open_captain(self.root), 1)
        self.start.assert_not_called()

    def test_installer_lock_blocks_startup(self):
        from feature_state import installation_lock
        with installation_lock(self.root):
            self.assertEqual(open_captain(self.root), 1)
        self.start.assert_not_called()
        self.open.assert_not_called()

    def test_generated_launcher_uses_checked_entrypoint(self):
        import installer
        with patch.object(installer.Path, 'home', return_value=self.root):
            installer.make_launcher(self.root)
        script = (self.root / 'Open Captain.command').read_text()
        self.assertIn('turnkey_install.py --root', script)
        self.assertNotIn('/usr/bin/open', script)
        self.assertEqual(script, (self.root / 'Start Local AI.command').read_text())

    def test_missing_installation_is_actionable(self):
        self.assertEqual(open_captain(self.root / 'missing'), 1)
        self.assertIn('Run Install LOCAL AI Core.command', self.output.getvalue())
        self.open.assert_not_called()


if __name__ == '__main__':
    unittest.main()
