"""Verify OpenAI inline picture is delivered to Ollama as image bytes."""
import base64
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model_engine import Engine
from model_team import preset


def inline_image():
    stream = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 50, 100)).save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


def body(url):
    return {"model": "local-ai", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "What is in this picture?"},
        {"type": "image_url", "image_url": {"url": url}}]}]}


class VisionGatewayTests(unittest.TestCase):
    def test_image_part_reaches_ollama_backend_without_network_fetch(self):
        cfg = {"text_models": {"local-ai": preset("coordinator")}}
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(cfg, root=Path(folder))
            seen = []
            def mocked_api(url, route, data=None, timeout=30):
                seen.append((route, data))
                if route == "/api/ps":
                    return {"models": []}
                if route == "/api/show":
                    return {"capabilities": ["completion", "vision"]}
                if route == "/api/chat":
                    return {"message": {"role": "assistant", "content": "Image received"}}
                return {}
            try:
                with patch("model_engine.api", side_effect=mocked_api), \
                     patch("model_engine.port_open", return_value=False), \
                     patch.object(engine, "stop_comfy"), \
                     patch.object(engine, "unload_ollama"):
                    response = engine.submit(body(inline_image())).result(3)
                self.assertEqual(response, "Image received")
                posted = [args for route, args in seen if route == "/api/chat"][0]
                self.assertEqual(len(posted["messages"][0]["images"]), 1)
                self.assertEqual(posted["messages"][0]["content"], "What is in this picture?")
                self.assertEqual(base64.b64decode(posted["messages"][0]["images"][0])[:2], bytes.fromhex("ffd8"))
            finally:
                engine.executor.shutdown(wait=True)

    def test_external_image_url_is_rejected_before_backend(self):
        cfg = {"text_models": {"local-ai": preset("coordinator")}}
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(cfg, root=Path(folder))
            try:
                with patch("model_engine.api") as backend:
                    with self.assertRaises(ValueError):
                        engine.submit(body("https://example.org/secret.jpg"))
                    backend.assert_not_called()
            finally:
                engine.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()

