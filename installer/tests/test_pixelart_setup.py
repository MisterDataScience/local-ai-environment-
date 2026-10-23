import hashlib
import json
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pixelart_setup as setup


def sibling(name, data):
    blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    return {"rfilename": name, "size": len(data), "blobId": blob}


class PixelArtSetupTests(unittest.TestCase):
    def test_downloads_both_pinned_repositories_and_writes_verified_manifest(self):
        data = {
            setup.BASE_REPOSITORY: {
                "model_index.json": b"{}",
                "transformer/weights.safetensors": b"model weights",
            },
            setup.LORA_REPOSITORY: {
                setup.LORA_FILENAME: b"lora weights",
                "README.md": b"card",
            },
        }
        metadata = {
            repo: {"sha": "commit-" + str(i), "siblings": [sibling(name, body) for name, body in files.items()]}
            for i, (repo, files) in enumerate(data.items())
        }
        downloaded = []

        def fetch(repo, token):
            self.assertEqual(token, "secret-token")
            return metadata[repo]

        def download(repo, revision, item, destination, token):
            self.assertEqual(revision, metadata[repo]["sha"])
            self.assertEqual(token, "secret-token")
            rel = Path(item["rfilename"])
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data[repo][item["rfilename"]])
            downloaded.append((repo, item["rfilename"]))

        with tempfile.TemporaryDirectory() as folder:
            manifest = setup.install_repositories(
                Path(folder), "secret-token", metadata_fetch=fetch, file_download=download,
                free_bytes=lambda _: 10**12,
            )
            path = Path(folder) / "models/pixelart/model-manifest.json"
            self.assertEqual(json.loads(path.read_text()), manifest)
            self.assertTrue(manifest["weights_verified"])
            self.assertEqual(manifest["generation"]["steps"], 4)
            self.assertEqual(manifest["base_model"]["revision"], "commit-0")
            self.assertEqual(manifest["pixelart_lora"]["revision"], "commit-1")
            self.assertEqual(len(downloaded), 4)
            self.assertNotIn("secret-token", path.read_text())

    def test_refuses_insufficient_space_before_downloading(self):
        metadata = {
            repo: {"sha": "commit", "siblings": [{"rfilename": "large.safetensors", "size": 20_000_000_000}]}
            for repo in (setup.BASE_REPOSITORY, setup.LORA_REPOSITORY)
        }
        download = Mock()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(setup.PixelArtSetupError, "need about"):
                setup.install_repositories(Path(folder), "token", metadata_fetch=lambda repo, token: metadata[repo],
                                           file_download=download, free_bytes=lambda _: 1)
        download.assert_not_called()

    def test_rejects_path_traversal_and_bad_hash_before_install(self):
        with self.assertRaises(setup.PixelArtSetupError):
            setup._safe_relative_path("../../outside")
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "repo"
            item = {"rfilename": "weights.safetensors", "size": 3,
                    "lfs": {"oid": "sha256:" + "0" * 64}}

            def fake_open(request, timeout=0):
                class Response:
                    status = 200
                    sent = False
                    def __enter__(self): return self
                    def __exit__(self, *args): return False
                    def read(self, _size):
                        if self.sent:
                            return b""
                        self.sent = True
                        return b"bad"
                    def close(self): pass
                return Response()

            with self.assertRaisesRegex(setup.PixelArtSetupError, "digest"):
                setup._download_file(setup.BASE_REPOSITORY, "rev", item, destination, "token",
                                     open_url=fake_open, log=lambda *args: None)

    def test_skip_is_default_and_does_not_ask_for_token(self):
        secret = Mock()
        output = Mock()
        selected = setup.install_if_selected(Path("/unused"), input_fn=lambda _prompt: "n",
                                             secret_fn=secret, output=output)
        self.assertFalse(selected)
        secret.assert_not_called()

    def test_owner_confirmation_precedes_token_prompt_and_download(self):
        inputs = iter(("yes", "yes"))
        token_prompted = []
        manifest = {"weights_verified": True}

        def fetch(_root, token, *, metadata_fetch):
            self.assertEqual(token, "secret-token")
            return manifest

        with unittest.mock.patch.object(setup, "install_repositories", side_effect=fetch):
            selected = setup.install_if_selected(
                Path("/unused"), input_fn=lambda _: next(inputs),
                secret_fn=lambda _: token_prompted.append(True) or "secret-token", output=lambda *_: None,
            )
        self.assertTrue(selected)
        self.assertEqual(token_prompted, [True])


if __name__ == "__main__":
    unittest.main()
