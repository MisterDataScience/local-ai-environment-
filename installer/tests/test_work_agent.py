import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'payload'))
import work_agent as w
from text_models import DEFAULT_TEXT_MODELS

class WorkAgentTests(unittest.TestCase):
    def test_local_provider_permissions_and_real_context_limits(self):
        cfg = w.configuration({'text_models': DEFAULT_TEXT_MODELS}, ['local-ai', 'local-ai-small'])
        self.assertEqual(cfg['enabled_providers'], ['local-ai-gateway'])
        provider = cfg['provider']['local-ai-gateway']
        self.assertEqual(provider['options']['baseURL'], 'http://127.0.0.1:8001/v1')
        self.assertEqual(provider['models']['local-ai']['limit']['context'], 16384)
        self.assertEqual(provider['models']['local-ai']['limit']['output'], 4096)
        self.assertEqual(provider['models']['local-ai']['limit']['input'], 12288)
        self.assertEqual(cfg['compaction']['reserved'], 2048)
        self.assertEqual(cfg['permission']['bash'], 'ask')
        self.assertEqual(cfg['permission']['edit'], 'ask')
        self.assertEqual(cfg['permission']['external_directory'], 'deny')
        self.assertEqual(cfg['permission']['webfetch'], 'deny')
        self.assertEqual(cfg['default_agent'], 'plan')
        self.assertFalse(cfg['autoupdate'])
        self.assertEqual(cfg['share'], 'disabled')

    def test_remote_browser_origin_is_exactly_the_private_tailnet(self):
        cfg = {'text_models': DEFAULT_TEXT_MODELS, 'remote_access': {
            'enabled': True, 'hostname': 'mac-mini.tailnet-name.ts.net',
            'captain_url': 'https://mac-mini.tailnet-name.ts.net:10000'}}
        settings = w.configuration(cfg, ['local-ai'])
        self.assertEqual(settings['server']['cors'],
                         ['https://mac-mini.tailnet-name.ts.net:10000'])
        self.assertNotIn('*', settings['server']['cors'])
        for address in ('https://untrusted.example.com:10000',
                        'http://mac-mini.tailnet-name.ts.net:10000',
                        'https://mac-mini.tailnet-name.ts.net:443',
                        'https://different.ts.net:10000'):
            with self.subTest(address=address):
                cfg['remote_access']['captain_url'] = address
                with self.assertRaises(ValueError):
                    w.configuration(cfg, ['local-ai'])

    def test_global_behaviour_is_passive_and_does_not_register_new_tools(self):
        from common import GLOBAL_BEHAVIOUR
        cfg = w.configuration({'text_models': DEFAULT_TEXT_MODELS}, ['local-ai'])
        for name in ('plan', 'build'):
            self.assertEqual(cfg['agent'][name]['prompt'], GLOBAL_BEHAVIOUR)
        self.assertIn('answer simple requests directly', GLOBAL_BEHAVIOUR)
        self.assertIn('Discover additional capabilities only when needed', GLOBAL_BEHAVIOUR)
        self.assertFalse(cfg['tools']['websearch'])
        self.assertFalse(cfg['tools']['webfetch'])
        self.assertFalse(cfg['tools']['task'])

    def test_webui_inherits_same_behaviour_without_forcing_account_override(self):
        from common import GLOBAL_BEHAVIOUR, webui_environment
        env = webui_environment(Path('/tmp/example'), {'api_key': 'key', 'webui_secret': 'secret'})
        system = json.loads(env['DEFAULT_INTERFACE_SETTINGS'])['system']
        self.assertTrue(system.startswith(GLOBAL_BEHAVIOUR))
        self.assertIn('LOCAL AI capabilities', system)
        self.assertIn('Tools are callable only when selected and permitted', system)
        self.assertNotIn('secret', system)
        self.assertNotIn('key', system)
        self.assertEqual(json.loads(env['DEFAULT_MODEL_PARAMS'])['function_calling'], 'native')

    def test_output_advertisement_matches_mode_and_custom_context(self):
        import copy
        for mode, expected in [('normal', 4096), ('max', 8192)]:
            cfg = w.configuration({'text_models': DEFAULT_TEXT_MODELS}, ['local-ai'], mode)
            self.assertEqual(cfg['provider']['local-ai-gateway']['models']['local-ai']['limit']['output'], expected)
        presets = copy.deepcopy(DEFAULT_TEXT_MODELS)
        presets['local-ai']['num_ctx'] = 4096
        cfg = w.configuration({'text_models': presets}, ['local-ai'], 'max')
        self.assertEqual(cfg['provider']['local-ai-gateway']['models']['local-ai']['limit']['output'], 2048)
        self.assertEqual(cfg['provider']['local-ai-gateway']['models']['local-ai']['limit']['input'], 2048)
        self.assertEqual(cfg['compaction']['reserved'], 1024)

    def test_project_copy_excludes_hooks_credentials_and_agent_config(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            src = root / 'src'
            src.mkdir()
            for name in ['main.py', '.env', 'opencode.json', 'AGENTS.md', 'private.pem']:
                (src / name).write_text('content')
            (src / '.git').mkdir()
            (src / '.git/config').write_text('credential')
            dest = root / 'copy'
            w.copy_project(src, dest)
            self.assertEqual([p.name for p in dest.iterdir()], ['main.py'])
            (dest / 'main.py').write_text('edited')
            self.assertEqual((src / 'main.py').read_text(), 'content')

    def test_symlink_and_size_failure_remove_incomplete_copy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            src = root / 'src'
            src.mkdir()
            (src / 'link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                w.copy_project(src, root / 'copy')
            self.assertFalse((root / 'copy').exists())
            (src / 'link').unlink()
            (src / 'big').write_bytes(b'12345')
            with self.assertRaises(ValueError):
                w.copy_project(src, root / 'copy', max_bytes=2)
            self.assertFalse((root / 'copy').exists())

    def test_environment_does_not_inherit_provider_or_account_keys(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'GITHUB_TOKEN':'sensitive', 'OPENAI_API_KEY':'sensitive', 'OPENCODE_CONFIG':'bad'}):
            env = w.environment(Path(d), {'api_key':'local-key'}, {})
            for key in ('GITHUB_TOKEN', 'OPENAI_API_KEY', 'OPENCODE_CONFIG'):
                self.assertNotIn(key, env)
            self.assertEqual(env['HOME'], os.environ['HOME'])
            self.assertEqual(env['OPENCODE_DISABLE_PROJECT_CONFIG'], 'true')
            self.assertEqual(env['LOCAL_AI_GATEWAY_KEY'], 'local-key')

    def test_native_code_execution_settings_are_explicit(self):
        from common import webui_environment
        env = webui_environment(Path('/tmp/example'), {'api_key': 'key', 'webui_secret': 'secret'})
        self.assertEqual(env['ENABLE_CODE_EXECUTION'], 'True')
        self.assertEqual(env['CODE_EXECUTION_ENGINE'], 'pyodide')
        self.assertEqual(env['ENABLE_CODE_INTERPRETER'], 'True')
        self.assertEqual(env['CODE_INTERPRETER_ENGINE'], 'pyodide')

    def test_launcher_blocks_gaming_before_workspace_creation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'control').mkdir()
            (root / 'control/config.json').write_text(json.dumps({'api_key': 'key'}))
            with patch.object(sys, 'argv', ['work_agent', '--root', d]), patch.object(w, 'http', return_value={'mode': 'gaming', 'transitioning': False, 'error': None}), patch.object(w.subprocess, 'Popen') as launch:
                with self.assertRaises(RuntimeError): w.main()
                launch.assert_not_called()
                self.assertFalse((root / 'work-agent').exists())

    def test_launcher_uses_native_web_and_stops_on_mode_change(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'control').mkdir()
            cfg = {'api_key': 'key', 'text_models': DEFAULT_TEXT_MODELS}
            (root / 'control/config.json').write_text(json.dumps(cfg))
            binary = root / 'tools/opencode' / w.VERSION / 'opencode'
            binary.parent.mkdir(parents=True)
            binary.write_text('mock')
            responses = [{'mode': 'normal', 'transitioning': False, 'error': None},
                         {'data': [{'id': 'local-ai'}]},
                         {'mode': 'gaming', 'transitioning': False, 'error': None}]
            process = Mock()
            process.pid = os.getpid()
            process.poll.return_value = None
            with patch.object(sys, 'argv', ['work_agent', '--root', d]), patch('required_tools_setup.verify'), patch('builtins.input', return_value=''), patch('builtins.print'), patch.object(w, 'http', side_effect=responses), patch.object(w, 'port_open', return_value=False), patch.object(w.subprocess, 'run'), patch.object(w.subprocess, 'Popen', return_value=process) as launch, patch.object(w, 'stop_process') as stop, patch.object(w.time, 'sleep'):
                w.main()
                self.assertEqual(launch.call_args.args[0][1:], ['web', '--hostname', '127.0.0.1', '--port', '4096'])
                self.assertIn('OPENCODE_SERVER_PASSWORD', launch.call_args.kwargs['env'])
                stop.assert_called_once_with(process, timeout=10)

    def test_install_checksum_failure_never_executes(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'downloads').mkdir()
            def download(url, path, checksum): path.write_bytes(b'bad')
            run = Mock()
            with self.assertRaises(ValueError): w.install(root, download, run)
            run.assert_not_called()

if __name__ == '__main__': unittest.main()


