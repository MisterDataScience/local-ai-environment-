import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import reverse_image_setup


class ReverseImageSetupTests(unittest.TestCase):
    def make_root(self, config):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "control").mkdir()
        (root / "control/config.json").write_text(json.dumps(config))
        return temporary, root

    def test_requires_vpn_proxy_and_workspace(self):
        base = {"web": {"enabled": True, "proxy_url": reverse_image_setup.PROXY_URL}}
        temporary, root = self.make_root(base)
        try:
            with self.assertRaisesRegex(RuntimeError, "AI Workspace"):
                reverse_image_setup.configure(root)
        finally:
            temporary.cleanup()

        temporary, root = self.make_root({"vault": {"enabled": True}, "web": {"enabled": True}})
        try:
            with self.assertRaisesRegex(RuntimeError, "Enable Web Access"):
                reverse_image_setup.configure(root)
        finally:
            temporary.cleanup()

    def test_saves_credentials_owner_only_without_echoing_key(self):
        config = {
            "api_key": "gateway-key",
            "web": {"enabled": True, "proxy_url": reverse_image_setup.PROXY_URL},
            "vault": {"enabled": True},
        }
        temporary, root = self.make_root(config)
        try:
            with patch("builtins.input", return_value="folder-id"), \
                 patch.object(reverse_image_setup.getpass, "getpass", return_value="search-key"):
                reverse_image_setup.configure(root)
            path = root / "control/config.json"
            saved = json.loads(path.read_text())
            self.assertEqual(saved["api_key"], "gateway-key")
            self.assertEqual(saved["reverse_image"], {
                "enabled": True,
                "provider": "yandex",
                "folder_id": "folder-id",
                "api_key": "search-key",
            })
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        finally:
            temporary.cleanup()

    def test_disable_preserves_other_configuration(self):
        config = {
            "web": {"enabled": True, "proxy_url": reverse_image_setup.PROXY_URL},
            "vault": {"enabled": True},
            "reverse_image": {"enabled": True, "provider": "yandex", "folder_id": "f", "api_key": "k"},
        }
        temporary, root = self.make_root(config)
        try:
            reverse_image_setup.configure(root, disable=True)
            saved = json.loads((root / "control/config.json").read_text())
            self.assertFalse(saved["reverse_image"]["enabled"])
            self.assertEqual(saved["reverse_image"]["api_key"], "k")
            self.assertTrue(saved["web"]["enabled"])
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
