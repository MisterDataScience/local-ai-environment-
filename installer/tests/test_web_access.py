import base64
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "payload"))
import web_access
import web_client

spec = importlib.util.spec_from_file_location("web_service", ROOT / "web/service.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def dns(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


class WebTests(unittest.TestCase):
    def test_release_images_are_immutable_and_use_arm64(self):
        for image in (*web_access.IMAGES.values(), web_access.BROWSER_IMAGE):
            self.assertRegex(image, r"^[^@]+@sha256:[0-9a-f]{64}$")
        spec = web_access.specification(dict(web_access.IMAGES, browser=web_access.BROWSER_IMAGE), True)
        self.assertTrue(all(x["platform"] == "linux/arm64" for x in spec["services"].values()))

    def test_image_pull_verifies_exact_digest_and_architecture(self):
        image = web_access.IMAGES["vpn"]
        valid = {"RepoDigests": [image], "Architecture": "arm64", "Os": "linux"}
        for details in (valid, dict(valid, RepoDigests=["other@sha256:" + "a" * 64]),
                        dict(valid, Architecture="amd64"), dict(valid, Os="windows")):
            with self.subTest(details=details), patch.object(web_access, "run") as run:
                run.return_value.stdout = json.dumps([details])
                if details == valid:
                    self.assertEqual(web_access.pull_verified_image("docker", image), image)
                else:
                    with self.assertRaises(RuntimeError):
                        web_access.pull_verified_image("docker", image)
                self.assertEqual(run.call_args_list[0].args[0],
                                 ["docker", "pull", "--platform", "linux/arm64", image])
        with patch.object(web_access, "run") as run:
            with self.assertRaises(ValueError):
                web_access.pull_verified_image("docker", "python:latest")
            run.assert_not_called()

    def test_reader_http_auth_and_supported_endpoints(self):
        server = service.ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
        server.busy = threading.BoundedSemaphore(2)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        with patch.dict(service.os.environ, {"WEB_API_KEY": "test-key"}), \
             patch.object(service, "vpn_ready"), \
             patch.object(service, "search", return_value={"sources": [{"url": "https://example.org"}]}):
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + "/health")
                self.assertEqual(error.exception.code, 401)
                request = Request(base + "/search", data=b'{"query":"test"}', headers={"Authorization": "Bearer test-key"})
                with urlopen(request) as response:
                    self.assertEqual(json.load(response)["sources"][0]["url"], "https://example.org")
                for path in ("/v1/models", "/proxy"):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + path, headers={"Authorization": "Bearer test-key"}))
                    self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_search_page_failure_labels_snippet_instead_of_inventing_page(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock()
        response.read.return_value = json.dumps({"results": [{"url": "https://example.org", "content": "snippet"}]}).encode()
        with patch.object(service, "vpn_ready"), patch.object(service.LOCAL, "open", return_value=response), \
             patch.object(service, "page", side_effect=ValueError("Page blocked")):
            source = service.search("test")["sources"][0]
            self.assertEqual(source["kind"], "search snippet")
            self.assertEqual(source["read_error"], "Page blocked")

    def test_compose_has_no_independent_network_or_dns_fallback(self):
        data = web_access.specification({k: "example@sha256:abc" for k in web_access.IMAGES})
        for name in ("reader", "search"):
            cfg = data["services"][name]
            self.assertEqual(cfg["network_mode"], "service:vpn")
            self.assertNotIn("ports", cfg)
            self.assertNotIn("networks", cfg)
            self.assertIn("./resolv.conf:/etc/resolv.conf:ro", cfg["volumes"])
        vpn = data["services"]["vpn"]
        self.assertEqual(vpn["ports"], ["127.0.0.1:8090:8090", "127.0.0.1:8888:8888"])
        self.assertEqual(vpn["environment"]["FREE_ONLY"], "on")
        self.assertEqual(vpn["environment"]["FIREWALL"], "on")
        self.assertEqual(vpn["environment"]["HTTPPROXY"], "on")
        self.assertEqual(vpn["environment"]["HTTPPROXY_LOG"], "off")
        self.assertEqual(vpn["environment"]["HTTPPROXY_LISTENING_ADDRESS"], ":8888")
        self.assertEqual(vpn["environment"]["HTTPPROXY_STEALTH"], "on")
        self.assertNotIn("FIREWALL_OUTBOUND_SUBNETS", vpn["environment"])
        self.assertNotIn("FIREWALL_VPN_INPUT_PORTS", vpn["environment"])

    def test_private_reserved_multicast_and_mixed_dns_rejected(self):
        for ip in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "0.0.0.0", "224.0.0.1", "::1", "fc00::1"):
            with self.subTest(ip=ip), patch.object(service.socket, "getaddrinfo", return_value=dns(ip)):
                with self.assertRaises(ValueError):
                    service.target("https://example.org")
        with patch.object(service.socket, "getaddrinfo", return_value=dns("1.1.1.1") + dns("10.0.0.1")):
            with self.assertRaises(ValueError):
                service.target("https://example.org")

    def test_schemes_credentials_ports_and_controls_rejected_before_dns(self):
        with patch.object(service.socket, "getaddrinfo") as resolve:
            for url in ("file:///etc/passwd", "http://user:pass@example.org", "https://example.org:8080", "http://example.org\n", None):
                with self.assertRaises(ValueError):
                    service.target(url)
            resolve.assert_not_called()

    def test_vpn_failure_prevents_dns_and_page_connection(self):
        with patch.object(service, "vpn_ready", side_effect=RuntimeError("VPN down")), \
             patch.object(service.socket, "getaddrinfo") as resolve, \
             patch.object(service.socket, "create_connection") as connect:
            with self.assertRaises(RuntimeError):
                service.page("https://example.org")
            resolve.assert_not_called()
            connect.assert_not_called()

    def test_vpn_health_failure_does_not_query_searxng(self):
        with patch.object(service, "vpn_ready", side_effect=RuntimeError("VPN down")), \
             patch.object(service.LOCAL, "open") as opened:
            with self.assertRaises(RuntimeError):
                service.search("test")
            opened.assert_not_called()

    def response(self, status=200, data=b"<title>Example</title><script>secret</script><p>Hello</p>", headers=None):
        response = Mock(status=status)
        values = {"Content-Type": "text/html", "Content-Encoding": "identity"}
        values.update(headers or {})
        response.getheader.side_effect = lambda name, default=None: values.get(name, default)
        response.headers.get_content_charset.return_value = "utf-8"
        response.read1.side_effect = [data, b""]
        return response

    def test_tls_uses_pinned_public_ip_and_original_hostname(self):
        conn = Mock()
        conn.getresponse.return_value = self.response()
        context = Mock()
        with patch.object(service, "vpn_ready"), \
             patch.object(service.socket, "getaddrinfo", return_value=dns("1.1.1.1")) as resolve, \
             patch.object(service.socket, "create_connection") as connect, \
             patch.object(service.ssl, "create_default_context", return_value=context), \
             patch.object(service.http.client, "HTTPConnection", return_value=conn):
            result = service.page("https://example.org/test")
            self.assertIn("Hello", result["text"])
            self.assertNotIn("secret", result["text"])
            self.assertEqual(result["title"], "Example")
            self.assertEqual(resolve.call_count, 1)
            self.assertEqual(connect.call_args.args[0], ("1.1.1.1", 443))
            self.assertEqual(context.wrap_socket.call_args.kwargs["server_hostname"], "example.org")
            conn.close.assert_called_once()

    def test_redirect_to_private_destination_revalidated(self):
        conn = Mock()
        conn.getresponse.return_value = self.response(302, headers={"Location": "https://localhost/admin"})
        with patch.object(service, "vpn_ready"), \
             patch.object(service.socket, "getaddrinfo", side_effect=[dns("1.1.1.1"), dns("127.0.0.1")]), \
             patch.object(service.socket, "create_connection") as connect, \
             patch.object(service.ssl, "create_default_context"), \
             patch.object(service.http.client, "HTTPConnection", return_value=conn):
            with self.assertRaises(ValueError):
                service.page("https://example.org")
            self.assertEqual(connect.call_count, 1)

    def test_pdf_and_compressed_responses_rejected(self):
        for headers in ({"Content-Type": "application/pdf"}, {"Content-Encoding": "gzip"}):
            conn = Mock()
            conn.getresponse.return_value = self.response(headers=headers)
            with patch.object(service, "vpn_ready"), patch.object(service, "target", return_value=(
                    service.urlsplit("http://example.org"), "example.org", 80, "1.1.1.1")), \
                 patch.object(service.socket, "create_connection"), \
                 patch.object(service.http.client, "HTTPConnection", return_value=conn):
                with self.assertRaises(ValueError):
                    service.page("http://example.org")

    def test_oversize_response_rejected(self):
        conn = Mock()
        conn.getresponse.return_value = self.response(data=b"x" * 101)
        with patch.object(service, "MAX_BYTES", 100), patch.object(service, "vpn_ready"), \
             patch.object(service, "target", return_value=(service.urlsplit("http://example.org"), "example.org", 80, "1.1.1.1")), \
             patch.object(service.socket, "create_connection"), \
             patch.object(service.http.client, "HTTPConnection", return_value=conn):
            with self.assertRaises(ValueError):
                service.page("http://example.org")

    def test_gateway_retrieves_only_loopback_and_preserves_source_links(self):
        cfg = {"web": {"enabled": True, "url": "http://127.0.0.1:8090", "api_key": "secret"}}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock()
        response.read.return_value = json.dumps({"sources": [{"url": "https://example.org/a(b)",
                                    "text": "x" * 1000, "title": "Title"}]}).encode()
        opener = Mock()
        opener.open.return_value = response
        with patch.object(web_client, "build_opener", return_value=opener):
            messages, links = web_client.retrieve(cfg, "read", "https://example.org/a(b) What changed?", 500)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:8090/read")
            self.assertEqual(json.loads(request.data)["url"], "https://example.org/a(b)")
            self.assertIn("What changed?", messages[1]["content"])
            self.assertIn("untrusted", messages[0]["content"])
            self.assertIn("a%28b%29", links)
            self.assertIn("truncated", links)

    def test_disabled_or_nonlocal_service_never_contacts_internet(self):
        with patch.object(web_client, "build_opener") as opener:
            for cfg in ({}, {"web": {"enabled": True, "url": "https://public.example"}}):
                with self.assertRaises(RuntimeError):
                    web_client.retrieve(cfg, "search", "test")
            opener.assert_not_called()

    def test_reinstall_migrates_enabled_browser_and_repairs_missing_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control").mkdir()
            (root / "control/config.json").write_text(json.dumps({"browser": {"enabled": True}}))
            web = root / "web"
            web.mkdir()
            (web / "vpn.env").write_text("existing-key")
            (web / "images.json").write_text('{"browser":"old:latest"}')
            expected = dict(web_access.IMAGES, browser=web_access.BROWSER_IMAGE)
            for attempt in range(2):
                with patch.object(web_access, "docker_command", return_value="docker"), \
                     patch.object(web_access, "pull_verified_image", side_effect=lambda binary, image: image) as pull, \
                     patch.object(web_access, "start"):
                    web_access.configure(root)
                    self.assertEqual([call.args[1] for call in pull.call_args_list], list(expected.values()))
                self.assertEqual(json.loads((web / "images.json").read_text()), expected)
                spec = json.loads((web / "compose.json").read_text())
                self.assertEqual(spec["services"]["browser"]["image"], web_access.BROWSER_IMAGE)

    def test_failed_release_pull_keeps_existing_image_and_compose_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control").mkdir()
            (root / "control/config.json").write_text('{}')
            web = root / "web"
            web.mkdir()
            (web / "vpn.env").write_text("existing-key")
            (web / "images.json").write_text('{"vpn":"previous"}')
            (web / "compose.json").write_text('{"previous":true}')
            with patch.object(web_access, "docker_command", return_value="docker"), \
                 patch.object(web_access, "pull_verified_image", side_effect=RuntimeError("pull failed")), \
                 patch.object(web_access, "start") as start:
                with self.assertRaisesRegex(RuntimeError, "pull failed"):
                    web_access.configure(root)
                start.assert_not_called()
            self.assertEqual((web / "images.json").read_text(), '{"vpn":"previous"}')
            self.assertEqual((web / "compose.json").read_text(), '{"previous":true}')
            self.assertEqual((root / "control/config.json").read_text(), '{}')

    def test_configure_preserves_config_and_records_private_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control").mkdir()
            (root / "control/config.json").write_text(json.dumps({"api_key": "old", "text_models": {"custom": 1}}))
            (root / "web").mkdir()
            (root / "web/images.json").write_text(json.dumps({k: "pinned@sha256:abc" for k in web_access.IMAGES}))
            with patch.object(web_access, "docker_command", return_value="docker"), \
                 patch.object(web_access.getpass, "getpass", return_value=base64.b64encode(b"x" * 32).decode()), \
                 patch.object(web_access, "pull_verified_image", side_effect=lambda binary, image: image), \
                 patch.object(web_access, "start"):
                web_access.configure(root)
            cfg = json.loads((root / "control/config.json").read_text())
            images = json.loads((root / "web/images.json").read_text())
            self.assertEqual(images, web_access.IMAGES)
            self.assertEqual(cfg["api_key"], "old")
            self.assertEqual(cfg["text_models"], {"custom": 1})
            self.assertEqual(cfg["web"]["url"], "http://127.0.0.1:8090")
            self.assertEqual(cfg["web"]["proxy_url"], "http://127.0.0.1:8888")
            self.assertEqual((root / "web/vpn.env").stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / "control/config.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / "web/resolv.conf").read_text().splitlines()[0], "nameserver 127.0.0.1")
            report = json.loads((root / "web-acceptance-report.json").read_text())
            self.assertEqual(report["vpn_drop_and_dns_leak_test"], "pending")


if __name__ == "__main__":
    unittest.main()
