import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tool_availability


class ToolAvailabilityTests(unittest.TestCase):
    CONFIG = {"api_key": "private-gateway-key", "webui_secret": "secret",
              "web": {"enabled": True}, "browser": {"enabled": True},
              "office": {"enabled": True}}

    def test_registration_matches_without_tool_invocation(self):
        from common import webui_environment
        declared = json.loads(webui_environment(Path("/test"), self.CONFIG)["TOOL_SERVER_CONNECTIONS"])
        calls = []
        def read(path, *, token=None, payload=None, port=8081):
            calls.append((port, path))
            if port == 8001:
                return {"paths": {"/capabilities/discover_local_capabilities": {
                    "post": {"operationId": "discover_local_capabilities"}}}}
            if path.endswith("/signin"):
                return {"token": "temporary-token"}
            return {"TOOL_SERVER_CONNECTIONS": declared}
        with patch.object(tool_availability, "request", side_effect=read):
            report = tool_availability.audit(self.CONFIG, Path("/test"))
        self.assertEqual(report["webui"], "registration_matches")
        self.assertEqual(report["gateway"], "discovery_spec_reachable")
        self.assertFalse(report["missing_servers"])
        self.assertEqual(report["per_chat_selection"], "not_verified")
        self.assertEqual(len(calls), 3)
        self.assertNotIn("temporary-token", json.dumps(report))
        self.assertNotIn("private-gateway-key", json.dumps(report))

    def test_missing_webui_registration_is_reported_without_autofixing(self):
        def read(path, *, token=None, payload=None, port=8081):
            if port == 8001:
                return {"paths": {"/capabilities/discover_local_capabilities": {
                    "post": {"operationId": "discover_local_capabilities"}}}}
            if path.endswith("/signin"):
                return {"token": "temporary-token"}
            return {"TOOL_SERVER_CONNECTIONS": []}
        with patch.object(tool_availability, "request", side_effect=read):
            report = tool_availability.audit(self.CONFIG, Path("/test"))
        self.assertEqual(report["webui"], "registration_mismatch")
        self.assertIn("local-ai-capabilities", report["missing_servers"])

    def test_closed_services_are_not_claimed_as_ready(self):
        with patch.object(tool_availability, "request", side_effect=URLError("offline")):
            report = tool_availability.audit(self.CONFIG, Path("/test"))
        self.assertEqual(report["gateway"], "not_reachable_or_not_updated")
        self.assertEqual(report["webui"], "not_reachable_or_registration_unverified")
        self.assertFalse(report["registered_servers"])

    def test_guarded_mode_registers_no_external_chat_servers(self):
        cfg = dict(self.CONFIG, desktop={"enabled": True})
        with patch.object(tool_availability, "request", side_effect=URLError("offline")):
            report = tool_availability.audit(cfg, Path("/test"))
        self.assertEqual(report["configured_servers"], [])
        self.assertEqual(report["per_chat_selection"], "not_verified")


if __name__ == "__main__":
    unittest.main()
