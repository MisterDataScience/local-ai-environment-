"""Regression tests for local multimodal messages and file boundaries."""
import base64
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "payload"))

from PIL import Image
from image_inputs import normalize_data_image
from tool_protocol import messages_for_ollama
from file_transfer import transfer
from pdf_reader import read_pdf
from pdf_mcp import dispatch as pdf_dispatch
from vault_transfer import transfer_vault
from unittest.mock import patch
from contextlib import contextmanager
import os


def image_url():
    output = BytesIO()
    Image.new("RGB", (24, 24), (30, 40, 50)).save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


class RequiredFeaturesTests(unittest.TestCase):
    def test_images_are_normalized_and_preserved(self):
        url = image_url()
        request = [{"role": "user", "content": [
            {"type": "text", "text": "Describe this"},
            {"type": "image_url", "image_url": {"url": url}}]}]
        message = messages_for_ollama(request)[0]
        self.assertEqual(message["content"], "Describe this")
        self.assertEqual(len(message["images"]), 1)
        with Image.open(BytesIO(base64.b64decode(message["images"][0]))) as result:
            self.assertEqual(result.format, "JPEG")

    def test_external_image_urls_and_bad_content_fail_closed(self):
        for url in ("https://example.org/image.png", "file:///etc/passwd",
                    "data:image/svg+xml;base64,PHN2Zz4="):
            with self.assertRaises(ValueError):
                normalize_data_image(url)
        with self.assertRaises(ValueError):
            messages_for_ollama([{"role": "system", "content": [
                {"type": "image_url", "image_url": {"url": image_url()}}]}])

    def test_file_transfer_only_between_explicit_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_id = "a" * 32
            project = root / "work-agent/projects" / project_id
            project.mkdir(parents=True)
            browser = root / "web/browser-outputs"
            browser.mkdir(parents=True)
            (browser / "paper.pdf").write_bytes(b"%PDF-1.4 test")
            dest = transfer(root, project_id, "paper.pdf")
            self.assertEqual(dest.read_bytes(), b"%PDF-1.4 test")
            with self.assertRaises(FileExistsError):
                transfer(root, project_id, "paper.pdf")
            with self.assertRaises(ValueError):
                transfer(root, project_id, "../secret.pdf")
            (browser / "escape.pdf").symlink_to(dest)
            with self.assertRaises(ValueError):
                transfer(root, project_id, "escape.pdf")

    def test_pdf_mcp_is_discoverable_and_has_project_scoping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            response = pdf_dispatch({"id": 1, "method": "initialize"}, root)
            self.assertEqual(response["result"]["serverInfo"]["name"], "local-ai-project-pdf")
            listing = pdf_dispatch({"id": 2, "method": "tools/list"}, root)
            self.assertEqual(listing["result"]["tools"][0]["name"], "read_pdf")
            denied = pdf_dispatch({"id": 3, "method": "tools/call", "params": {
                "name": "read_pdf", "arguments": {"path": "../secret.pdf"}}}, root)
            self.assertEqual(denied["error"]["code"], -32602)

    def test_explicit_vault_transfer_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_id = "a" * 32
            project = root / "work-agent/projects" / project_id
            project.mkdir(parents=True)
            vault = root / "mockvault"
            for folder in ("Inbox", "Projects", "Outputs", "Archive"):
                (vault / folder).mkdir(parents=True)
            (vault / "Inbox/source.pdf").write_bytes(b"%PDF-test")
            @contextmanager
            def mounted(_):
                fd = os.open(vault, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    yield fd
                finally:
                    os.close(fd)
            with patch("vault_transfer.mounted_root", mounted):
                result = transfer_vault({}, root, project_id, "Inbox/source.pdf", "vault-import")
                self.assertIn("PLAINTEXT", result)
                self.assertEqual((project / "Inbox/source.pdf").read_bytes(), b"%PDF-test")
                with self.assertRaises(FileExistsError):
                    transfer_vault({}, root, project_id, "Inbox/source.pdf", "vault-import")
                result = transfer_vault({}, root, project_id, "Inbox/source.pdf", "vault-export")
                self.assertIn("encrypted workspace", result)
                self.assertEqual((vault / "Outputs/source.pdf").read_bytes(), b"%PDF-test")
                with self.assertRaises(ValueError):
                    transfer_vault({}, root, project_id, "../outside.pdf", "vault-import")

    def test_pdf_reader_rejects_files_outside_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises((ValueError, FileNotFoundError)):
                read_pdf("../secret.pdf", root)


if __name__ == "__main__":
    unittest.main()
