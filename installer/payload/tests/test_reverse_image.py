import io
import json
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import reverse_image


class FakeResponse:
    def __init__(self, body, status=200):
        self.status_code = status
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size=65536):
        yield self.body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.trust_env = True
        self.proxies = {}
        self.calls = []
        self.closed = False

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response

    def close(self):
        self.closed = True


class ReverseImageTests(unittest.TestCase):
    def config(self):
        return {
            "web": {
                "enabled": True,
                "url": "http://127.0.0.1:8090",
                "proxy_url": reverse_image.PROXY_URL,
                "api_key": "local-web-key",
            },
            "reverse_image": {
                "enabled": True,
                "provider": "yandex",
                "folder_id": "folder",
                "api_key": "yandex-key",
            },
        }

    def test_sanitise_reencodes_without_metadata(self):
        source = Image.new("RGB", (80, 50), (10, 20, 30))
        data = io.BytesIO()
        exif = Image.Exif()
        exif[0x010E] = "private-description"
        source.save(data, format="JPEG", exif=exif)
        clean, width, height = reverse_image.sanitise_image(data.getvalue())
        self.assertLessEqual(len(clean), reverse_image.MAX_UPLOAD_BYTES)
        with Image.open(io.BytesIO(clean)) as result:
            self.assertEqual(result.format, "JPEG")
            self.assertEqual(result.getexif().get(0x010E), None)
            self.assertEqual((width, height), result.size)

    def test_wrong_or_missing_proxy_fails_before_network(self):
        config = self.config()
        for value in (None, "http://127.0.0.1:9999", "https://proxy.example"):
            config["web"]["proxy_url"] = value
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "VPN proxy"):
                reverse_image._configured(config)

    def test_vpn_failure_prevents_yandex_request(self):
        session = Mock()
        config = self.config()
        with patch.object(reverse_image, "_vpn_ready", side_effect=RuntimeError("VPN down")), \
             patch.object(reverse_image.requests, "Session", return_value=session):
            with self.assertRaisesRegex(RuntimeError, "VPN down"):
                reverse_image._search_yandex(config, b"jpeg")
        session.post.assert_not_called()

    def test_yandex_uses_only_explicit_proxy_and_blocks_redirects(self):
        response = FakeResponse({"images": [{
            "url": "https://images.example/a.jpg",
            "pageUrl": "https://example.org/source",
            "pageTitle": "Example",
            "host": "example.org",
            "passage": "Match",
            "format": "jpg",
            "width": 100,
            "height": 80,
        }]})
        session = FakeSession(response)
        with patch.object(reverse_image, "_vpn_ready"), \
             patch.object(reverse_image.requests, "Session", return_value=session):
            matches = reverse_image._search_yandex(self.config(), b"jpeg")
        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies, {"http": reverse_image.PROXY_URL, "https": reverse_image.PROXY_URL})
        self.assertEqual(len(session.calls), 1)
        args, kwargs = session.calls[0]
        self.assertEqual(args[0], reverse_image.YANDEX_ENDPOINT)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Api-Key yandex-key")
        self.assertEqual(kwargs["json"]["folderId"], "folder")
        self.assertEqual(matches[0]["page_url"], "https://example.org/source")
        self.assertTrue(session.closed)

    def test_non_web_result_urls_are_not_returned(self):
        response = FakeResponse({"images": [
            {"url": "local:invalid", "pageUrl": "https://user:pass@example.org"},
            {"url": "https://images.example/good.jpg", "pageUrl": "custom:invalid"},
        ]})
        session = FakeSession(response)
        with patch.object(reverse_image, "_vpn_ready"), \
             patch.object(reverse_image.requests, "Session", return_value=session):
            matches = reverse_image._search_yandex(self.config(), b"jpeg")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["image_url"], "https://images.example/good.jpg")
        self.assertIsNone(matches[0]["page_url"])

    def test_tool_returns_only_sanitised_metadata_and_matches(self):
        config = self.config()
        with patch.object(reverse_image, "_workspace_image", return_value=b"original"), \
             patch.object(reverse_image, "sanitise_image", return_value=(b"derivative", 640, 480)), \
             patch.object(reverse_image, "_search_yandex", return_value=[{"page_url": "https://example.org"}]) as search:
            result = reverse_image.search_tool(config, "Inbox/private-name.jpg")
        search.assert_called_once_with(config, b"derivative")
        self.assertEqual(result["sanitised_dimensions"], {"width": 640, "height": 480})
        self.assertNotIn("workspace_path", result)
        self.assertNotIn("private-name", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
