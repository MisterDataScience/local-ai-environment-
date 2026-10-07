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
    def test_compaction_uses_small_context_ceiling_and_active_model(self):
        env = common.webui_environment(Path('/test'), {'webui_secret': 'secret', 'api_key': 'key'})
        self.assertEqual(env['ENABLE_CONTEXT_COMPACTION'], 'True')
        self.assertLess(int(env['CONTEXT_COMPACTION_TOKEN_CAP']) + 2048, 4096)
        self.assertEqual(env['CONTEXT_COMPACTION_TOKEN_THRESHOLD'], env['CONTEXT_COMPACTION_TOKEN_CAP'])
        self.assertEqual(env['CONTEXT_COMPACTION_MODEL'], '')

    def test_gateway_manifest_contains_every_runtime_module(self):
        payload = installer.SOURCE / "payload"
        expected = {p.name for p in payload.glob("*.py") if p.name != "check-workflows.py"}
        self.assertEqual(set(installer.GATEWAY_FILES), expected)

    def test_any_gateway_module_change_invalidates_native_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = root / "control"
            for name in installer.GATEWAY_FILES + installer.TEAM_FILES + ("workflows/image.json", "workflows/video.json", "config.json", "comfy_vault/__init__.py"):
                path = control / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("initial")
            baseline = installer.acceptance_fingerprint(root)
            for name in installer.GATEWAY_FILES + installer.TEAM_FILES:
                path = control / name
                path.write_text("changed")
                self.assertNotEqual(baseline, installer.acceptance_fingerprint(root), name)
                path.write_text("initial")
                self.assertEqual(baseline, installer.acceptance_fingerprint(root))

    def test_existing_text_configuration_is_migrated_without_losing_settings(self):
        config = {"text_model": "custom:7b", "thinking": True,
                  "api_key": "existing-secret", "render_timeout_seconds": 900}
        upgraded = installer.upgrade_text_configuration(config)
        self.assertNotIn("text_models", config)
        self.assertEqual(upgraded["api_key"], "existing-secret")
        self.assertEqual(upgraded["render_timeout_seconds"], 900)
        self.assertEqual(upgraded["text_models"]["local-ai"]["model"], "custom:7b")
        self.assertEqual(upgraded["text_models"]["local-ai"]["num_ctx"], 8192)
        self.assertTrue(upgraded["text_models"]["local-ai"]["thinking"])
        self.assertEqual(len(upgraded["text_models"]), 3)
        upgraded["text_models"]["local-ai-small"]["keep_alive_seconds"] = 45
        self.assertEqual(installer.upgrade_text_configuration(upgraded), upgraded)

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

    def test_stock_context_upgrade_is_once_only_and_preserves_custom_settings(self):
        import copy
        from text_models import DEFAULT_TEXT_MODELS, configured_text_models
        presets = copy.deepcopy(DEFAULT_TEXT_MODELS)
        presets['local-ai']['num_ctx'] = 8192
        presets['local-ai']['keep_alive_seconds'] = 45
        presets['local-ai-small']['num_ctx'] = 4096
        presets['local-ai-large']['num_ctx'] = 4096
        source = {'api_key': 'unchanged', 'text_models': presets}
        upgraded = installer.upgrade_text_configuration(source)
        self.assertEqual([p['num_ctx'] for p in upgraded['text_models'].values()], [16384] * 3)
        self.assertEqual(upgraded['text_models']['local-ai']['keep_alive_seconds'], 45)
        self.assertEqual(upgraded['api_key'], 'unchanged')
        self.assertEqual(source['text_models']['local-ai']['num_ctx'], 8192)
        # An intentional later reduction must survive subsequent installer runs.
        upgraded['text_models']['local-ai']['num_ctx'] = 8192
        self.assertEqual(installer.upgrade_text_configuration(upgraded), upgraded)
        presets['local-ai']['num_ctx'] = 6144
        presets['local-ai-large']['model'] = 'custom:7b'
        custom = installer.upgrade_text_configuration(source)
        self.assertEqual(custom['text_models']['local-ai']['num_ctx'], 6144)
        self.assertEqual(custom['text_models']['local-ai-large']['num_ctx'], 4096)
        presets['local-ai']['num_ctx'] = 16385
        with self.assertRaises(ValueError):
            configured_text_models(source)

    def test_native_cutoff_acceptance_requires_length_signal(self):
        with patch.object(installer, 'http', return_value={
                'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}],
                'usage': {'completion_tokens': 8}}) as request:
            result = installer.verify_text_cutoff('test-key', 'local-ai')
        self.assertEqual(result['finish_reason'], 'length')
        self.assertEqual(request.call_args.args[1]['max_completion_tokens'], 8)
        with patch.object(installer, 'http', return_value={'choices': [{'finish_reason': 'stop'}]}):
            with self.assertRaises(RuntimeError):
                installer.verify_text_cutoff('test-key', 'local-ai')

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

    def test_native_tool_configuration_uses_server_side_vpn_connection(self):
        config = {"api_key": "gateway-key", "webui_secret": "secret", "web": {"enabled": True, "api_key": "reader-key"}}
        env = common.webui_environment(Path("/test"), config)
        self.assertEqual(env["ENABLE_TOOL_PERMISSIONS"], "True")
        self.assertEqual(json.loads(env["DEFAULT_MODEL_PARAMS"])["tool_approval_mode"], "ask")
        server = json.loads(env["TOOL_SERVER_CONNECTIONS"])[0]
        self.assertEqual(server["url"], "http://127.0.0.1:8001")
        self.assertEqual(server["auth_type"], "bearer")
        self.assertEqual(server["key"], "gateway-key")
        self.assertNotIn("reader-key", env["TOOL_SERVER_CONNECTIONS"])
        self.assertEqual(env["ENABLE_WEB_SEARCH"], "False")
        self.assertEqual(env["ENABLE_IMAGE_GENERATION"], "False")

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

