import io
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import required_tools_setup as required


class RequiredToolsTests(unittest.TestCase):
    def test_playwright_only_checked_when_configured(self):
        servers, tools = required.expected_capabilities({})
        self.assertEqual(servers, ['projectpdf', 'projectfiles', 'projectvision'])
        self.assertNotIn('playwright_browser_navigate', tools)
        settings = {'mcp': {'playwright': {'enabled': True}}}
        servers, tools = required.expected_capabilities(settings)
        self.assertIn('playwright', servers)
        self.assertEqual(tools['playwright_browser_snapshot'], 'allow')
        self.assertEqual(tools['playwright_browser_navigate'], 'ask')
        self.assertEqual(tools['playwright_browser_type'], 'ask')
        self.assertEqual(tools['playwright_browser_evaluate'], 'ask')
        self.assertNotIn('playwright', required.expected_capabilities(
            {'mcp': {'playwright': {'enabled': False}}})[0])

    def test_effective_browser_permissions_are_verified(self):
        settings = {'mcp': {'playwright': {'enabled': True}}}
        servers, tools = required.expected_capabilities(settings)
        status = {server: {'status': 'connected'} for server in servers}
        agents = [{'name': role, 'permission': [
            {'permission': name, 'pattern': '*', 'action': action}
            for name, action in tools.items()
        ]} for role in ('plan', 'build')]
        def response(request, timeout=None):
            result = agents if request.full_url.endswith('/agent') else status
            return io.BytesIO(json.dumps(result).encode())
        env = {'OPENCODE_SERVER_PASSWORD': 'temporary',
               'OPENCODE_CONFIG_CONTENT': json.dumps(settings)}
        with patch.object(required, 'urlopen', side_effect=response):
            required.verify(Mock(poll=lambda: None), env, timeout=1)
        agents[1]['permission'][-1]['action'] = 'allow'
        with patch.object(required, 'urlopen', side_effect=response):
            with self.assertRaisesRegex(RuntimeError, 'permission mismatch'):
                required.verify(Mock(poll=lambda: None), env, timeout=1)


if __name__ == '__main__':
    unittest.main()
