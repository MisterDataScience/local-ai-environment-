import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import capability_discovery
import http_api


class CapabilityDiscoveryTests(unittest.TestCase):
    def test_small_schema_single_read_only_operation(self):
        spec = capability_discovery.specification()
        path = spec["paths"]["/capabilities/discover_local_capabilities"]
        self.assertEqual(path["post"]["operationId"], "discover_local_capabilities")
        self.assertEqual(len(spec["paths"]), 1)
        self.assertEqual(spec["security"], [{"bearerAuth": []}])

    def test_configured_vs_selected_and_credentials_never_disclosed(self):
        config = {"api_key": "top-secret", "web": {"enabled": True},
                  "browser": {"enabled": True}, "vault": {"enabled": True},
                  "office": {"enabled": True}, "model_team": {"enabled": True},
                  "account_tools": {"github": True}}
        result = capability_discovery.discover(config, {})
        found = {entry["category"]: entry for entry in result["capabilities"]}
        self.assertTrue(all(found[k]["configured"] for k in
                            ("web", "files", "workspace", "browser", "office", "coding",
                             "media", "accounts")))
        self.assertEqual(result["status"], "configuration_only")
        self.assertIn("current-chat", result["notice"])
        self.assertNotIn("top-secret", json.dumps(result))
        filtered = capability_discovery.discover(config, {"category": "browser"})
        self.assertEqual(len(filtered["capabilities"]), 1)
        self.assertEqual(filtered["capabilities"][0]["category"], "browser")

    def test_guarded_automation_hides_ordinary_interfaces(self):
        config = {"web": {"enabled": True}, "browser": {"enabled": True},
                  "office": {"enabled": True}, "desktop": {"enabled": True},
                  "model_team": {"enabled": True}}
        result = capability_discovery.discover(config, {})
        found = {entry["category"]: entry["configured"] for entry in result["capabilities"]}
        self.assertTrue(found["desktop"])
        for name in ("web", "files", "browser", "office", "coding"):
            self.assertFalse(found[name], name)
        # Explicit gateway media commands remain configured separately from integrations.
        self.assertTrue(found["media"])

    def test_rejects_invalid_arguments(self):
        for args in (None, [], {"category": "shell"}, {"category": 3},
                     {"category": "web", "token": "secret"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                capability_discovery.discover({}, args)

    def test_gateway_requires_auth_and_does_not_expose_media_listener(self):
        engine = Mock(config={"api_key": "test-key", "web": {"enabled": True}})
        for handler in (http_api.Handler, http_api.MediaHandler):
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server.engine = engine
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with self.assertRaises(HTTPError) as denied:
                    urlopen(base + "/capabilities/openapi.json", timeout=2)
                self.assertEqual(denied.exception.code, 401 if handler is http_api.Handler else 404)
                headers = {"Authorization": "Bearer test-key", "Content-Type": "application/json"}
                req = Request(base + "/capabilities/openapi.json", headers=headers)
                if handler is http_api.Handler:
                    with urlopen(req, timeout=2) as response:
                        self.assertIn("discover_local_capabilities",
                                      response.read().decode())
                else:
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(req, timeout=2)
                    self.assertEqual(denied.exception.code, 404)
                req = Request(base + "/capabilities/discover_local_capabilities",
                              headers=headers, data=b'{"category":"web"}')
                if handler is http_api.Handler:
                    with urlopen(req, timeout=2) as response:
                        result = json.load(response)
                    self.assertEqual(result["capabilities"][0]["category"], "web")
                    self.assertEqual(result["status"], "configuration_only")
                    bad = Request(base + "/capabilities/discover_local_capabilities",
                                  headers=headers, data=b'{"category":"shell"}')
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(bad, timeout=2)
                    self.assertEqual(denied.exception.code, 400)
                else:
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(req, timeout=2)
                    self.assertEqual(denied.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)


if __name__ == "__main__":
    unittest.main()
