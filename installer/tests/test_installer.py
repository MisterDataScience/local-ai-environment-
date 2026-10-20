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
    def test_comfy_dependencies_upgrade_when_old_checkpoint_has_unpinned_torch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comfy = root / 'ComfyUI'
            (comfy / '.venv/bin').mkdir(parents=True)
            (comfy / 'main.py').write_text('old existing ComfyUI source')
            (comfy / '.venv/bin/python').write_text('fake installed Python')
            state = root / 'install-state.json'
            installer.checkpoint(state, 'comfy-dependencies')
            with patch.object(installer, 'ensure_comfy_source', return_value=comfy), \
                 patch.object(installer, 'run') as runner:
                installer.install_comfy(root, Path('/tmp/uv'), state)
                first = [call.args[0] for call in runner.call_args_list]
                self.assertTrue(any('--require-hashes' in cmd for cmd in first))
                self.assertTrue(any('--only-binary' in cmd for cmd in first))
                runner.reset_mock()
                installer.install_comfy(root, Path('/tmp/uv'), state)
                # Second run only checks existing exact versions and MPS.
                self.assertEqual(runner.call_count, 1)
            marker = json.loads((comfy / '.local-ai-dependencies.json').read_text())
            self.assertEqual(marker['torch'], '2.10.0')
            self.assertTrue(installer.completed(state, 'comfy-dependencies'))

    def test_failed_comfy_dependency_upgrade_never_claims_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comfy = root / 'ComfyUI'
            (comfy / '.venv/bin').mkdir(parents=True)
            (comfy / 'main.py').write_text('source')
            (comfy / '.venv/bin/python').write_text('venv')
            state = root / 'install-state.json'
            installer.checkpoint(state, 'comfy-dependencies')
            def failing_run(command, **_):
                if command[0] == comfy / '.venv/bin/python':
                    raise RuntimeError('MPS compatibility failed')
            with patch.object(installer, 'ensure_comfy_source', return_value=comfy), \
                 patch.object(installer, 'run', side_effect=failing_run):
                with self.assertRaisesRegex(RuntimeError, 'MPS compatibility failed'):
                    installer.install_comfy(root, Path('/tmp/uv'), state)
            self.assertFalse((comfy / '.local-ai-dependencies.json').exists())

    def test_upgrade_native_acceptance_temporarily_sets_max_then_restores_user_mode(self):
        import resource_modes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'control').mkdir()
            resource_modes.save(root / 'control', 'normal')
            observed = []
            def check(*args):
                observed.append(resource_modes.load(root / 'control'))
            with patch.object(installer, 'verify_generation', side_effect=check):
                installer.verify_generation_during_install(root, {})
            self.assertEqual(observed, ['max'])
            self.assertEqual(resource_modes.load(root / 'control'), 'normal')

    def test_failed_upgrade_acceptance_restores_gaming_without_fake_success(self):
        import resource_modes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'control').mkdir()
            resource_modes.save(root / 'control', 'gaming')
            with patch.object(installer, 'verify_generation', side_effect=RuntimeError('model failed')):
                with self.assertRaisesRegex(RuntimeError, 'model failed'):
                    installer.verify_generation_during_install(root, {})
            self.assertEqual(resource_modes.load(root / 'control'), 'gaming')

    def test_compaction_uses_small_context_ceiling_and_active_model(self):
        env = common.webui_environment(Path('/test'), {'webui_secret': 'secret', 'api_key': 'key'})
        self.assertEqual(env['ENABLE_CONTEXT_COMPACTION'], 'True')
        self.assertLess(int(env['CONTEXT_COMPACTION_TOKEN_CAP']) + 2048, 4096)
        self.assertEqual(env['CONTEXT_COMPACTION_TOKEN_THRESHOLD'], env['CONTEXT_COMPACTION_TOKEN_CAP'])
        self.assertEqual(env['CONTEXT_COMPACTION_MODEL'], '')

    def test_gateway_manifest_contains_every_runtime_module(self):
        payload = installer.SOURCE / "payload"
        expected = {p.name for p in payload.glob("*.py") if p.name != "check-workflows.py"}
        expected.update(("commons.html", "institutions.html"))
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

    def test_completed_interrupted_model_download_promotes_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'model.gguf'
            partial = destination.with_name(destination.name + '.part')
            content = b'verified-completed-model'
            partial.write_bytes(content)
            checksum = hashlib.sha256(content).hexdigest()
            with patch.object(installer, 'run') as runner:
                installer.download('https://example.test/model', destination, checksum)
            runner.assert_not_called()
            self.assertEqual(destination.read_bytes(), content)
            self.assertFalse(partial.exists())

    def test_cached_complete_zip_is_promoted_and_partial_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'ComfyUI.zip'
            partial = destination.with_name(destination.name + '.part')
            with zipfile.ZipFile(partial, 'w') as archive:
                archive.writestr('ComfyUI-v0.38.0/main.py', 'pass')
            with patch.object(installer, 'run') as runner:
                installer.download('https://example.test/comfy.zip', destination)
            runner.assert_not_called()
            self.assertTrue(zipfile.is_zipfile(destination))
            destination.unlink()
            partial.symlink_to(Path(temporary) / 'unrelated')
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                installer.download('https://example.test/model', destination)

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

    def test_acceptance_observes_both_ollama_backends_and_native_release(self):
        presets = {'local-ai': {'model': 'fallback'}, 'local-ai-captain': {'model': 'shared'}}
        cfg = {'captain': {'enabled': True, 'model_id': 'local-ai-captain', 'provider': 'ollama'}}
        with patch.object(installer, 'http', side_effect=[{'models': []}, {'models': [{'name': 'shared'}]}]) as http:
            installer.verify_text_residency(cfg, presets, 'local-ai-captain')
            self.assertEqual(http.call_count, 2)
        with patch.object(installer, 'http', side_effect=[{'models': []}, {'models': [{'name': 'shared'}]}]):
            with self.assertRaisesRegex(RuntimeError, 'Unexpected resident'):
                installer.verify_text_residency(cfg, presets, None)
        cfg['captain']['provider'] = 'llama'
        with patch.object(installer, 'http', return_value={'models': []}), patch.object(installer, 'port_open', return_value=True):
            installer.verify_text_residency(cfg, presets, 'local-ai-captain')
            with self.assertRaisesRegex(RuntimeError, 'GGUF residency'):
                installer.verify_text_residency(cfg, presets, None)

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

    def test_read_only_discovery_server_is_registered_but_not_automatically_selected(self):
        env = common.webui_environment(Path("/test"), {
            "api_key": "gateway-key", "webui_secret": "secret"
        })
        connections = json.loads(env["TOOL_SERVER_CONNECTIONS"])
        catalogue = [c for c in connections if c["info"]["id"] == "local-ai-capabilities"]
        self.assertEqual(len(catalogue), 1)
        self.assertEqual(catalogue[0]["path"], "capabilities/openapi.json")
        self.assertEqual(catalogue[0]["auth_type"], "bearer")
        self.assertNotIn("tool_ids", env)
        self.assertNotIn("TOOL_SEARCH_ALWAYS_LOADED", env)

    def test_host_environment_cannot_inject_unapproved_tool_server(self):
        with patch.dict(common.os.environ, {"TOOL_SERVER_CONNECTIONS": json.dumps([
                {"info": {"id": "untrusted"}, "url": "https://outside.invalid"}])}):
            env = common.webui_environment(Path("/test"), {
                "api_key": "gateway-key", "webui_secret": "secret"})
        servers = json.loads(env["TOOL_SERVER_CONNECTIONS"])
        self.assertNotIn("untrusted", [s["info"]["id"] for s in servers])
        self.assertNotIn("outside.invalid", env["TOOL_SERVER_CONNECTIONS"])

    def test_guarded_automation_does_not_advertise_webui_tools(self):
        env = common.webui_environment(Path("/test"), {
            "api_key": "gateway-key", "webui_secret": "secret",
            "web": {"enabled": True}, "browser": {"enabled": True},
            "desktop": {"enabled": True}
        })
        self.assertNotIn("TOOL_SERVER_CONNECTIONS", env)
        self.assertEqual(env["ENABLE_CODE_EXECUTION"], "False")
        self.assertEqual(env["ENABLE_CODE_INTERPRETER"], "False")

    def test_shutdown_waits_for_owned_process(self):
        process = Mock(pid=123)
        with patch.object(common.os, "killpg") as kill:
            common.stop_process(process, timeout=4200)
        kill.assert_called_once_with(123, common.signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=4200)

    def test_check_tool_availability_launcher_has_executable_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "control").mkdir()
            with patch.object(installer.Path, "home", return_value=root):
                installer.make_launcher(root)
            script = (root / "Check Tool Availability.command").read_text()
            self.assertEqual(script.splitlines()[0], "#!/bin/bash")
            self.assertEqual(script.splitlines()[1], "set -e")
            self.assertIn("tool_availability.py --root ", script.splitlines()[3])
            self.assertNotIn(r"\n", script)

    def test_autonomous_worker_is_packaged_and_launchers_require_job_id(self):
        self.assertIn("autonomous_jobs.py", installer.TEAM_FILES)
        self.assertTrue((installer.SOURCE / "autonomous_jobs.py").is_file())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "control").mkdir()
            with patch.object(installer.Path, "home", return_value=root):
                installer.make_launcher(root)
            for label, flag in (
                ("Create Autonomous Job", "--configure"),
                ("Autonomous Job Status", "--status"),
                ("Stop Autonomous Job", "--stop"),
                ("Resume Autonomous Job", "--resume")
            ):
                script = (root / (label + ".command")).read_text()
                self.assertIn("autonomous_jobs.py --root ", script)
                self.assertIn(flag, script)
                self.assertIn('"$@"', script)
                self.assertEqual(script.splitlines()[0], "#!/bin/bash")

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

