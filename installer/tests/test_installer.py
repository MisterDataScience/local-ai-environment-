import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common
import installer


class InstallerTests(unittest.TestCase):
    def test_download_verifies_and_reuses_completed_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "model"
            content = b"verified model"
            checksum = hashlib.sha256(content).hexdigest()
            def fake_run(command, **kwargs):
                Path(command[command.index("-o") + 1]).write_bytes(content)
            with patch.object(installer, "run", side_effect=fake_run) as runner:
                installer.download("https://example.test/model", destination, checksum)
                installer.download("https://example.test/model", destination, checksum)
            self.assertEqual(destination.read_bytes(), content)
            self.assertEqual(runner.call_count, 1)

    def test_interrupted_download_keeps_partial_for_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "model"
            partial = destination.with_name("model.part")
            partial.write_bytes(b"partial")
            with patch.object(installer, "run", side_effect=RuntimeError("network offline")):
                with self.assertRaises(RuntimeError):
                    installer.download("https://example.test/model", destination, "checksum")
            self.assertEqual(partial.read_bytes(), b"partial")
            self.assertFalse(destination.exists())

    def test_wrong_hash_never_becomes_installed_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "model"
            def fake_run(command, **kwargs):
                Path(command[command.index("-o") + 1]).write_bytes(b"wrong")
            with patch.object(installer, "run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    installer.download("https://example.test/model", destination, "0" * 64)
            self.assertFalse(destination.exists())
            self.assertEqual(len(list(Path(temporary).glob("*.invalid-*"))), 1)

    def test_source_archive_cannot_escape_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("../outside.txt", "bad")
            with self.assertRaises(ValueError):
                installer.extract_zip(archive, Path(temporary) / "extracted")
            self.assertFalse((Path(temporary) / "outside.txt").exists())

    def test_checkpoint_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            installer.checkpoint(path, "installed")
            installer.checkpoint(path, "installed")
            self.assertEqual(json.loads(path.read_text())["completed"], ["installed"])
            self.assertTrue(installer.completed(path, "installed"))
            self.assertFalse(installer.completed(path, "unknown"))

    def test_chat_configuration_only_targets_local_gateway(self):
        config = {"api_key": "local-key", "webui_secret": "secret"}
        env = common.webui_environment(Path("/test"), config)
        self.assertEqual(env["OPENAI_API_BASE_URL"], "http://127.0.0.1:8001/v1")
        self.assertEqual(env["ENABLE_OLLAMA_API"], "False")
        self.assertEqual(env["ENABLE_TITLE_GENERATION"], "False")
        self.assertEqual(env["WEBUI_AUTH"], "False")
        self.assertEqual(env["ENABLE_PERSISTENT_CONFIG"], "False")

    def test_ollama_has_private_model_store_and_one_worker(self):
        env = common.ollama_environment(Path("/test"))
        self.assertEqual(env["OLLAMA_MODELS"], "/test/models/ollama")
        self.assertEqual(env["OLLAMA_NUM_PARALLEL"], "1")
        self.assertEqual(env["OLLAMA_HOST"], "127.0.0.1:11435")

    def test_shutdown_waits_for_owned_process(self):
        process = Mock(pid=123)
        with patch.object(common.os, "killpg") as kill:
            common.stop_process(process, timeout=4200)
        kill.assert_called_once_with(123, common.signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=4200)

    def test_unrelated_application_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            application = root / "Applications/Local AI.app"
            application.mkdir(parents=True)
            (application / "keep.txt").write_text("keep")
            with patch.object(installer.Path, "home", return_value=root):
                with self.assertRaises(RuntimeError):
                    installer.make_launcher(root)
            self.assertEqual((application / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
