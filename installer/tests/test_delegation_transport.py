"""MCP handshake must select only a recognised host-code tool."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from delegation_browser import MCP
from control_policy import Blocked


class TransportTests(unittest.TestCase):
    def test_current_and_legacy_tool_names(self):
        for name in ('browser_run_code_unsafe', 'browser_run_code'):
            with self.subTest(name=name):
                client = MCP()
                client.request = Mock(side_effect=[{'serverInfo': {'name': 'test'}}, None,
                    {'tools': [{'name': name}]}])
                client.connect()
                self.assertEqual(client.code_tool, name)
                self.assertEqual(client.request.call_args_list[1].args[0], 'notifications/initialized')
                self.assertEqual(client.request.call_count, 3)

    def test_missing_tool_cannot_fall_back_to_arbitrary_browser_controls(self):
        client = MCP()
        client.request = Mock(side_effect=[{'serverInfo': {'name': 'test'}}, None,
            {'tools': [{'name': 'browser_evaluate'}, {'name': 'browser_type'}]}])
        with self.assertRaises(Blocked):
            client.connect()
        self.assertIsNone(client.code_tool)


if __name__ == '__main__':
    unittest.main()
