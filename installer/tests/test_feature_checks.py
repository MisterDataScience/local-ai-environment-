"""Acceptance protocol and interrupted VPN diagnostic recovery contracts."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
from feature_checks import MCP, recover_web_acceptance
from feature_state import atomic_json


class NativeFeatureCheckContracts(unittest.TestCase):
    def response(self, content):
        response = io.BytesIO(content.encode())
        response.headers = {'Mcp-Session-Id': 'private-session'}
        return response

    def test_mcp_handles_pretty_json_sse_notifications_and_session_ids(self):
        client = MCP('http://127.0.0.1:8931/mcp')
        client.opener = Mock()
        client.opener.open.side_effect = [
            self.response(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'serverInfo': {'name': 'test'}}}, indent=2)),
            self.response(''),
            self.response('event: message\ndata: ' + json.dumps({'jsonrpc': '2.0', 'id': 3, 'result': {'tools': []}}) + '\n\n')]
        client.initialise()
        self.assertEqual(client.call('tools/list'), {'tools': []})
        request = client.opener.open.call_args_list[-1].args[0]
        self.assertEqual(request.get_header('Mcp-session-id'), 'private-session')
        self.assertEqual(json.loads(client.opener.open.call_args_list[1].args[0].data)['method'], 'notifications/initialized')

    def test_mcp_error_is_not_accepted_as_an_identity_check(self):
        client = MCP('http://127.0.0.1:8931/mcp')
        client.opener = Mock()
        client.opener.open.return_value = self.response(json.dumps({'id': 1, 'result': {'isError': True}}))
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            client.call('tools/call', {'name': 'get_me'})

    def test_interrupted_tunnel_test_restores_original_config_before_removing_credential(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'web').mkdir()
            auth = root / 'web/acceptance-auth-private.toml'
            auth.write_text('private-key')
            original = {'services': {'vpn': {'image': 'preserved-pin'}}}
            atomic_json(root / 'web/acceptance-recovery.json', {'original_spec': original, 'auth_file': auth.name})
            atomic_json(root / 'web/compose.json', {'services': {'temporary': True}})
            with patch('web_access.start', side_effect=RuntimeError('Docker not ready')):
                with self.assertRaises(RuntimeError):
                    recover_web_acceptance(root)
            self.assertTrue(auth.is_file())
            self.assertTrue((root / 'web/acceptance-recovery.json').is_file())
            self.assertEqual(json.loads((root / 'web/compose.json').read_text()), original)
            with patch('web_access.start'):
                recover_web_acceptance(root)
                recover_web_acceptance(root)
            self.assertFalse(auth.exists())
            self.assertFalse((root / 'web/acceptance-recovery.json').exists())


if __name__ == '__main__':
    unittest.main()
