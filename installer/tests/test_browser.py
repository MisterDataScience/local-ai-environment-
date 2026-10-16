"""Static acceptance checks for optional VPN-only Playwright MCP wiring."""
import sys
import unittest
from unittest.mock import patch
import browser_setup
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_agent import configure as configure_agent
from web_access import IMAGES, specification
from common import webui_environment


class BrowserIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.images = {name: f"example/{name}@sha256:abc" for name in IMAGES}
        self.images["browser"] = "mcr.microsoft.com/playwright/mcp@sha256:abc"

    def test_browser_pulls_the_release_digest(self):
        with patch.object(browser_setup, "pull_verified_image", return_value=browser_setup.IMAGE) as pull:
            self.assertEqual(browser_setup.image_digest("docker"), browser_setup.IMAGE)
            pull.assert_called_once_with("docker", browser_setup.IMAGE)
        self.assertRegex(browser_setup.IMAGE, r"@sha256:[0-9a-f]{64}$")

    def test_browser_disabled_by_default(self):
        spec = specification(self.images)
        self.assertNotIn("browser", spec["services"])
        self.assertNotIn("127.0.0.1:8931:8931", spec["services"]["vpn"]["ports"])

    def test_vpn_namespace_is_mandatory(self):
        spec = specification(self.images, browser_enabled=True)
        browser = spec["services"]["browser"]
        self.assertEqual(browser["network_mode"], "service:vpn")
        self.assertEqual(browser["image"], self.images["browser"])
        self.assertIn("127.0.0.1:8931:8931", spec["services"]["vpn"]["ports"])
        self.assertIn("--headless", browser["command"])
        self.assertIn("--user-data-dir", browser["command"])
        self.assertEqual(browser["cap_drop"], ["ALL"])
        self.assertNotIn("ports", browser)
        self.assertEqual(browser["depends_on"]["vpn"]["condition"], "service_healthy")

    def test_missing_browser_digest_fails_closed(self):
        with self.assertRaises(ValueError):
            specification({name: self.images[name] for name in IMAGES}, browser_enabled=True)

    def test_work_agent_only_connects_when_both_enabled(self):
        for cfg in ({}, {"web": {"enabled": True}}, {"browser": {"enabled": True}}):
            settings = {"permission": {}, "agent": {"plan": {}, "build": {}}}
            configure_agent(settings, cfg)
            self.assertNotIn("playwright", settings.get("mcp", {}))
        settings = {"permission": {}, "agent": {"plan": {}, "build": {}}}
        configure_agent(settings, {"web": {"enabled": True}, "browser": {"enabled": True}})
        self.assertEqual(settings["mcp"]["playwright"]["url"], "http://127.0.0.1:8931/mcp")
        self.assertEqual(settings["agent"]["build"]["permission"]["playwright_browser_click"], "ask")
        self.assertEqual(settings["agent"]["plan"]["permission"]["playwright_browser_snapshot"], "allow")

    def test_chat_integration_stays_opt_in(self):
        cfg = {"webui_secret": "test", "api_key": "test",
               "web": {"enabled": True}, "browser": {"enabled": True}}
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            env = webui_environment(Path(directory), cfg)
        connections = json.loads(env["TOOL_SERVER_CONNECTIONS"])
        self.assertTrue(any(x.get("url") == "http://127.0.0.1:8931/mcp" for x in connections))


if __name__ == "__main__":
    unittest.main()
