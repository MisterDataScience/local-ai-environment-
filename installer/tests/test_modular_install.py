"""Core/feature lifecycle regressions. All native model tests remain Mac gates."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
import feature_state as state
import feature_install as features
import installer
from model_team import preset
from model_engine import Engine
from capability_discovery import discover
from turnkey_install import acceptance_summary, write_receipt


class ModularInstallTests(unittest.TestCase):
    def root(self, folder):
        root = Path(folder).resolve()
        (root / 'control').mkdir()
        config = installer.core_configuration(root, {'api_key': 'private-key', 'webui_secret': 'private-webui'})
        state.atomic_json(root / 'control/config.json', config)
        state.write(root, 'core', 'ready', acceptance={'native-captain-team': 'passed'})
        return root, config

    def test_fresh_core_has_only_one_small_fallback_and_preserves_customised_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root, fresh = self.root(folder)
            self.assertEqual(set(fresh['text_models']), {'local-ai'})
            self.assertEqual(fresh['text_models']['local-ai']['model'], preset('coordinator')['model'])
            self.assertNotIn('speech', fresh)
            for feature in state.FEATURES:
                if feature != 'core':
                    self.assertEqual(state.read(root, feature)['status'], 'not_installed')
            original = copy.deepcopy(fresh)
            original.update(vault={'enabled': True, 'id': 'approved-vault', 'mount_path': '/Volumes/Private'},
                            web={'enabled': True, 'api_key': 'preserve-me'},
                            speech={'enabled': True, 'voice': 'owner'},
                            account_tools={'github': True})
            original['text_models']['local-ai']['num_ctx'] = 6144
            original['text_models']['local-ai-custom'] = {**preset('coordinator'), 'name': 'Owner preset'}
            changed = installer.core_configuration(root, original)
            self.assertEqual(changed, original)
            # The runtime view hides optional capabilities without touching owner settings.
            view = state.effective_config(root, changed)
            self.assertFalse(view['web']['enabled'])
            self.assertFalse(view['speech']['enabled'])
            self.assertFalse(view['account_tools']['github'])
            self.assertEqual(view['vault'], original['vault'])
            self.assertEqual(changed['web']['api_key'], 'preserve-me')
            self.assertNotIn('private-key', json.dumps(state.snapshot(root)))

    def test_trial_migration_restores_deferred_settings_once_without_losing_selected_captain(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config = self.root(folder)
            config['install_profile'] = 'local-trial'
            backup = root / 'control/trial-deferred-settings.json'
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                installer.core_configuration(root, config)
            config['text_models']['local-ai-selected'] = {**preset('coordinator'), 'name': 'Selected'}
            state.atomic_json(backup, {'text_models': {'local-ai-restored': preset('document')},
                                      'vault': {'enabled': True, 'id': 'original'}})
            migrated = installer.core_configuration(root, config)
            self.assertIn('local-ai-selected', migrated['text_models'])
            self.assertIn('local-ai-restored', migrated['text_models'])
            self.assertEqual(migrated['vault']['id'], 'original')
            self.assertEqual(installer.core_configuration(root, migrated), migrated)
            self.assertTrue(backup.is_file())

    def test_core_environment_never_installs_optional_models_or_rewrites_owner_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config = self.root(folder)
            config.update(speech={'enabled': True, 'owner_option': 'preserve'},
                          vault={'enabled': True, 'id': 'owner-vault'})
            state.atomic_json(root / 'control/config.json', config)
            with patch.object(installer, 'run'), patch('dependency_locks.install_locked', return_value={}), \
                 patch('webui_local_images.harden'), patch('webui_local_images.harden_pdf'), \
                 patch('voice_setup.install', side_effect=AssertionError('Core downloaded speech')), \
                 patch('conversation_setup.install', side_effect=AssertionError('Core downloaded STT')):
                result = installer.install_environments(root, Path('/uv'), root / 'install-state.json', core=True)
            self.assertEqual(result['speech'], config['speech'])
            self.assertEqual(result['vault'], config['vault'])
            self.assertFalse((root / 'ComfyUI').exists())
            self.assertTrue((root / 'control/feature_install.py').is_file())
            self.assertTrue((root / 'control/installer.py').is_file())

    def test_default_main_finishes_without_optional_onboarding_and_everything_continues(self):
        from contextlib import ExitStack
        for extra, expected in (([], []), (['--everything'], list(features.INSTALLERS))):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as folder:
                root, config = self.root(folder)
                config['captain'] = {'enabled': True, 'provider': 'llama'}
                state.atomic_json(root / 'control/config.json', config)
                (root / 'webui').mkdir()
                @contextmanager
                def temporary_services(*args, **kwargs):
                    yield config
                with ExitStack() as stack:
                    stack.enter_context(patch.object(sys, 'argv', ['installer.py', '--root', str(root), '--uv', '/uv', *extra]))
                    for name in ('preflight', 'install_ollama', 'run', 'verify_generation_during_install'):
                        stack.enter_context(patch.object(installer, name))
                    stack.enter_context(patch.object(installer, 'install_environments', return_value=config))
                    stack.enter_context(patch.object(installer, 'acceptance_fingerprint', return_value='fingerprint'))
                    stack.enter_context(patch.object(installer, 'make_launcher', return_value=root / 'Start Local AI.command'))
                    stack.enter_context(patch('work_agent.install'))
                    stack.enter_context(patch('captain_setup.install_minicpm', return_value=config))
                    stack.enter_context(patch('feature_install.ensure_stopped'))
                    feature = stack.enter_context(patch('feature_install.run_feature', return_value=False))
                    stack.enter_context(patch('feature_checks.services', temporary_services))
                    stack.enter_context(patch('turnkey_install.acceptance_summary', return_value={'passed_checks': ['native-captain-team']}))
                    stack.enter_context(patch('turnkey_install.await_background', return_value={'webui_health': 'passed'}))
                    stack.enter_context(patch('turnkey_install.write_receipt', return_value={'pending_physical_acceptance': []}))
                    stack.enter_context(patch('turnkey_install.start_login_service'))
                    stack.enter_context(patch('turnkey_install.open_local_ui'))
                    self.assertEqual(installer.main(), 0)
                    self.assertEqual([call.args[1] for call in feature.call_args_list], expected)
                self.assertEqual(state.read(root, 'core')['status'], 'ready')

    def test_atomic_receipts_reject_links_and_lock_conflicts_do_not_mutate_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root, _ = self.root(folder)
            before = state.read(root, 'core')
            with state.installation_lock(root):
                with self.assertRaisesRegex(RuntimeError, 'active'):
                    with state.installation_lock(root):
                        self.fail('Concurrent writer admitted')
                with self.assertRaisesRegex(RuntimeError, 'active'):
                    with state.installation_lock(root, shared=True):
                        self.fail('Runtime admitted during mutation')
            self.assertEqual(state.read(root, 'core'), before)
            with state.installation_lock(root, shared=True):
                with self.assertRaises(RuntimeError):
                    with state.installation_lock(root):
                        self.fail('Installer admitted while runtime active')
            path = state.state_path(root, 'speech')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            outside = root / 'keep.json'
            outside.write_text('preserve')
            path.unlink()
            path.symlink_to(outside)
            with self.assertRaisesRegex(RuntimeError, 'Symbolic'):
                state.write(root, 'speech', 'ready')
            self.assertEqual(outside.read_text(), 'preserve')

    def test_speech_missing_wav_is_resumable_and_does_not_run_native_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config = self.root(folder)
            settings = {'enabled': True, 'model_revision': 'pinned'}
            with patch('voice_setup.install', return_value=settings) as install, \
                 patch('feature_install.prompt', return_value=''), \
                 patch('feature_checks.speech') as check:
                self.assertFalse(features.run_feature(root, 'speech', Path('/uv')))
                install.assert_called_once()
                check.assert_not_called()
            row = state.read(root, 'speech')
            self.assertEqual(row['status'], 'awaiting_user')
            self.assertEqual(row['installed_version'], 'pinned')
            self.assertIn('16-bit PCM WAV', row['next_action'])
            self.assertEqual(state.read(root, 'core')['status'], 'ready')
            self.assertEqual(features.configuration(root)['api_key'], config['api_key'])
            # An installed reference on a later day resumes the same module only.
            (root / 'voice-engine/voices').mkdir(parents=True)
            (root / 'voice-engine/voices/default.json').write_text('{}')
            with patch('voice_setup.install', return_value=settings), \
                 patch('feature_checks.speech', return_value={'speech_generation': 'passed'}), \
                 patch('feature_install.prompt', side_effect=AssertionError('Unexpected prompt')):
                self.assertTrue(features.run_feature(root, 'speech', Path('/uv')))
            self.assertEqual(state.read(root, 'speech')['status'], 'ready')

    def test_dependency_refusal_and_invalid_discord_token_are_feature_local(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config = self.root(folder)
            with patch.dict(features.INSTALLERS, {'discord': Mock()}):
                self.assertFalse(features.run_feature(root, 'discord', Path('/uv')))
                features.INSTALLERS['discord'].assert_not_called()
            self.assertIn('Install Live Conversation.command', state.read(root, 'discord')['next_action'])
            state.write(root, 'speech', 'ready')
            state.write(root, 'conversation', 'ready')
            with patch.dict(features.INSTALLERS, {'discord': Mock(side_effect=RuntimeError('Discord setup request failed (HTTP 401). secret-token'))}):
                self.assertFalse(features.run_feature(root, 'discord', Path('/uv')))
            row = state.read(root, 'discord')
            self.assertEqual(row['status'], 'failed')
            self.assertIn('HTTP 401', row['next_action'])
            self.assertNotIn('secret-token', json.dumps(row))
            self.assertEqual(state.read(root, 'core')['status'], 'ready')

    def test_failed_acceptance_never_advertises_ready_and_source_upgrades_require_recheck(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config = self.root(folder)
            with patch.dict(features.INSTALLERS, {'office': lambda *_: lambda: {'mcp': 'not_run'}}):
                self.assertFalse(features.run_feature(root, 'office', Path('/uv')))
            self.assertEqual(state.read(root, 'office')['status'], 'failed')
            state.write(root, 'web', 'ready')
            state.write(root, 'browser', 'ready')
            config.update(web={'enabled': True}, browser={'enabled': True})
            self.assertTrue(state.effective_config(root, config)['browser']['enabled'])
            state.write(root, 'web', 'failed')
            self.assertFalse(state.effective_config(root, config)['browser']['enabled'])
            code = root / 'control/voice_setup.py'
            code.write_text('revision one')
            state.write(root, 'speech', 'ready')
            config['speech'] = {'enabled': True}
            self.assertTrue(state.effective_config(root, config)['speech']['enabled'])
            code.write_text('revision two')
            self.assertFalse(state.effective_config(root, config)['speech']['enabled'])

    def test_registry_corruption_hides_optional_feature_without_blocking_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config = self.root(folder)
            state.state_path(root, 'web').write_text('{broken')
            view = state.effective_config(root, config)
            self.assertEqual(view['_feature_status']['web'], 'failed')
            self.assertEqual(view['text_models'], config['text_models'])
            self.assertEqual(state.snapshot(root)['web']['last_failure'], 'InvalidReceipt')
            self.assertFalse(features.run_feature(root, 'web', Path('/uv')))
            # An unrelated feature can still complete.
            with patch.dict(features.INSTALLERS, {'office': lambda *_: lambda: {'mcp': 'passed'}}):
                self.assertTrue(features.run_feature(root, 'office', Path('/uv')))

    def test_gateway_refuses_unready_routes_before_loading_models(self):
        engine = object.__new__(Engine)
        engine.config = {'feature_schema': 1, '_feature_status': {}}
        engine.text_models = {'local-ai': preset('coordinator')}
        engine.pause_commons = lambda *_: None
        for command, installer_name in (
            ('/image a tree', 'Install Image and Video.command'),
            ('/video a tree', 'Install Image and Video.command'),
            ('/speak hello', 'Install Local Speech.command'),
            ('/search trees', 'Install Encrypted Web Access.command')):
            with self.subTest(command=command):
                with self.assertRaisesRegex(ValueError, installer_name):
                    engine.submit({'model': 'local-ai', 'messages': [{'role': 'user', 'content': command}]})

    def test_native_core_requires_real_worker_retirement_but_no_optional_tests(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config = self.root(folder)
            config['captain'] = {'enabled': True, 'provider': 'llama', 'model_id': 'local-ai-captain'}
            config['text_models']['local-ai-captain'] = {**preset('coordinator'), 'backend': 'llama'}
            checks = [{'name': name, 'status': 'passed'} for name in ('text', 'text-local-ai', 'text-local-ai-captain')]
            state.atomic_json(root / 'acceptance-report.json', {'checks': checks})
            with self.assertRaisesRegex(RuntimeError, 'native-captain-team'):
                acceptance_summary(root, config)
            checks.append({'name': 'native-captain-team', 'status': 'passed'})
            state.atomic_json(root / 'acceptance-report.json', {'checks': checks})
            self.assertIn('native-captain-team', acceptance_summary(root, config)['passed_checks'])
            receipt = write_receipt(root, config, acceptance_summary(root, config), {'captain_visible': 'passed'})
            self.assertEqual(receipt['profile'], 'core')
            self.assertEqual(receipt['features']['web']['status'], 'not_installed')
            self.assertEqual(receipt['integration_acceptance']['vpn_web'], 'not_configured')

    def test_discovery_gives_exact_installer_without_exposing_secrets(self):
        result = discover({'feature_schema': 1, '_feature_status': {}, 'api_key': 'private'}, {'category': 'media'})
        row = result['capabilities'][0]
        self.assertFalse(row['configured'])
        self.assertIn('Install Image and Video.command', json.dumps(row))
        self.assertNotIn('private', json.dumps(result))

    def test_generated_launchers_execute_real_modules_and_preserve_argument_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='local ai ') as folder:
            root, config = self.root(folder)
            features.make_launchers(root)
            for feature, (name, _, _) in state.FEATURES.items():
                if feature == 'core': continue
                path = root / name
                self.assertTrue(path.stat().st_mode & 0o111)
                self.assertIn(' --feature ' + feature + ' "$@"', path.read_text())
                result = __import__('subprocess').run(['bash', '-n', str(path)], capture_output=True)
                self.assertEqual(result.returncode, 0)
            self.assertIn('--status', (root / 'Check LOCAL AI Setup.command').read_text())
            self.assertIn('--test-discord', (root / 'Test Discord Voice.command').read_text())


if __name__ == '__main__':
    unittest.main()
