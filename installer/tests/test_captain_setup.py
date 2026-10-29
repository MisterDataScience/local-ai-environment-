import tempfile
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from captain_config import upgrade
from model_team import upgrade_team, team_roles
from text_models import upgrade_text_configuration
from captain_setup import configure, select_artifacts, build_tools, download_artifact, install_minicpm, LLAMA_REVISION
import work_agent
import captain_setup
import captain_check
from common import ollama_environment


class CaptainSetupTests(unittest.TestCase):
    def test_usage_cli_reads_authenticated_report_without_running_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'control').mkdir()
            (root / 'control/config.json').write_text(json.dumps({'api_key': 'test-key'}))
            with patch('sys.argv', ['captain_check', '--root', folder, '--usage']), \
                 patch('urllib.request.build_opener') as opener, \
                 patch.object(captain_check, 'verify') as verify, \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(b'{"totals":{"requests":4}}')
                captain_check.main()
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:8001/control/usage')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')
            self.assertEqual(opener.call_args.args[0].proxies, {})
            self.assertEqual(json.loads(output.getvalue())['totals']['requests'], 4)
            verify.assert_not_called()
            self.assertFalse((root / 'captain-acceptance-report.json').exists())

    def metadata(self):
        base = {'sha': captain_setup.MODEL_REVISION, 'siblings': [
            {'rfilename': name, 'lfs': {'sha256': checksum}}
            for name, checksum in captain_setup.MODEL_FILES.values()]}
        adapter = {'sha': captain_setup.ADAPTER_REVISION, 'siblings': [
            {'rfilename': captain_setup.ADAPTER_FILENAME,
             'lfs': {'sha256': captain_setup.ADAPTER_SHA256}}]}
        return base, adapter

    def config(self):
        return upgrade(upgrade_team(upgrade_text_configuration({'text_model': 'qwen3:14b'})))

    def test_native_worker_permissions_share_one_model_and_no_worker_can_delegate(self):
        cfg = self.config()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'control').mkdir()
            for name in ('opencode-team.mjs', 'captain.mjs', 'essay-edit-prompt.txt', 'reverse-scaffold-prompt.txt'):
                (root / 'control' / name).write_text('test')
            settings = work_agent.configuration(cfg, list(cfg['text_models']), 'max', root,
                                               {'instance_id': 'gateway', 'epoch': 0, 'mode': 'max'})
            for role in ('researcher', 'analyst', 'coder', 'writer', 'reviewer'):
                worker = settings['agent']['captain-' + role]
                self.assertEqual(worker['model'], settings['agent']['plan']['model'])
                self.assertEqual(worker['permission']['*'], 'deny')
                self.assertNotIn('task', worker['permission'])
            self.assertEqual(settings['agent']['captain-coder']['permission']['edit'], 'ask')
            self.assertNotIn('edit', settings['agent']['captain-reviewer']['permission'])
            self.assertEqual(settings['agent']['captain-reviewer']['permission']['village_facilities'], 'allow')
            self.assertEqual(settings['agent']['captain-coder']['permission']['village_publish'], 'ask')
            self.assertNotIn('village_practice_prepare', settings['agent']['captain-coder']['permission'])
            self.assertFalse(settings['tools']['village_publish'])
            self.assertFalse(settings['tools']['team_run'])  # host policy enables after initialization

    def test_captain_and_worker_style_reaches_both_native_agents(self):
        cfg = self.config()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'control').mkdir()
            for name in ('opencode-team.mjs', 'captain.mjs', 'essay-edit-prompt.txt', 'reverse-scaffold-prompt.txt'):
                (root / 'control' / name).write_text('test')
            settings = work_agent.configuration(cfg, list(cfg['text_models']), 'max', root,
                                               {'instance_id': 'gateway', 'epoch': 0, 'mode': 'max'})
            for name in ('plan', 'build'):
                prompt = settings['agent'][name]['prompt']
                self.assertIn(captain_setup.CAPTAIN_RESPONSE_STYLE, prompt)
                self.assertIn('You are the captain', prompt)
                self.assertLess(len(prompt), 5500)
                self.assertIn('studio_contact', prompt)
                self.assertIn('pixelart_contact', prompt)
                self.assertIn('Route requests to create, redesign or repair a studio through studio_contact to The Synod', prompt)
                self.assertFalse(settings['tools']['studio_contact'])
            for role in captain_setup.ROLES:
                prompt = settings['agent']['captain-' + role]['prompt']
                self.assertIn(captain_setup.WORKER_REPORT_STYLE, prompt)
                self.assertIn('Work only on your assigned objective', prompt)

    def test_scoped_automation_cannot_activate_the_team(self):
        cfg = self.config(); cfg['desktop'] = {'enabled': True}
        settings = {'agent': {}, 'tools': {}}
        configure(cfg, settings, Path('/missing'), None)
        self.assertNotIn('plugin', settings)

    def test_parallel_runner_does_not_multiply_specialist_context_allocations(self):
        root = Path('/selected-root')
        single, shared = ollama_environment(root), ollama_environment(root, parallel=5, port=11436)
        self.assertEqual(single['OLLAMA_NUM_PARALLEL'], '1')
        self.assertEqual(shared['OLLAMA_NUM_PARALLEL'], '5')
        self.assertEqual(single['OLLAMA_MODELS'], shared['OLLAMA_MODELS'])
        self.assertNotEqual(single['OLLAMA_HOST'], shared['OLLAMA_HOST'])

    def test_model_downloads_use_an_immutable_revision_and_checksums_without_phone_shards(self):
        metadata, adapter = self.metadata()
        artifacts = select_artifacts(metadata, adapter)
        self.assertIn('/resolve/' + captain_setup.MODEL_REVISION + '/', artifacts['model']['url'])
        self.assertIn('/resolve/' + captain_setup.ADAPTER_REVISION + '/', artifacts['lora']['url'])
        self.assertEqual(artifacts['lora']['sha256'], captain_setup.ADAPTER_SHA256)
        metadata['siblings'][0]['rfilename'] = 'model-mix_q3gud_im-les.gguf'
        with self.assertRaisesRegex(RuntimeError, 'layout changed'):
            select_artifacts(metadata, adapter)

    def test_changed_or_missing_adapter_cannot_select_plain_model(self):
        import copy
        base, adapter = self.metadata()
        for change in ('revision', 'hash', 'missing'):
            broken = copy.deepcopy(adapter)
            if change == 'revision':
                broken['sha'] = 'f' * 40
            elif change == 'hash':
                broken['siblings'][0]['lfs']['sha256'] = '0' * 64
            else:
                broken['siblings'] = []
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                select_artifacts(base, broken)

    def test_shared_role_mapping_can_retire_unused_specialist_downloads(self):
        cfg = self.config(); cfg['captain']['single_model'] = True
        for role in ('analyst', 'coder'):
            del cfg['text_models'][cfg['model_team']['roles'][role]]
        roles = team_roles(cfg, cfg['text_models'])
        self.assertEqual({roles[r] for r in ('coordinator', 'analyst', 'coder')}, {'local-ai-captain'})
        self.assertEqual(cfg['text_models'][roles['document']]['num_ctx'], 32768)

    def test_fresh_mac_build_tools_use_the_private_environment_without_homebrew(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('tools/uv/uv', 'control/.venv/bin/python'):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture')
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                if 'pip' in command:
                    (root / 'control/.venv/bin/cmake').write_text('private cmake')
                from subprocess import CompletedProcess
                return CompletedProcess(command, 0)
            with patch('captain_setup.platform.system', return_value='Darwin'), patch('captain_setup.shutil.which', return_value=None), patch('captain_setup.subprocess.run', side_effect=run):
                self.assertEqual(build_tools(root), str(root / 'control/.venv/bin/cmake'))
            installation = next(c for c in calls if 'pip' in c)
            self.assertIn(str(root / 'control/.venv/bin/python'), installation)
            self.assertTrue(any('control-macos-arm64-py311.txt' in str(p) for p in installation))
            self.assertIn('--require-hashes', installation)

    def test_standalone_download_preserves_partial_and_resumes_with_checksum(self):
        import subprocess
        from shared_llama import digest
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'model.gguf'
            partial = target.with_suffix('.gguf.download')
            partial.write_bytes(b'part')
            expected = Path(folder) / 'expected'; expected.write_bytes(b'complete-model')
            checksum = digest(expected)
            with patch('captain_setup.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'curl')):
                with self.assertRaises(subprocess.CalledProcessError):
                    download_artifact('https://example.org/model', target, checksum)
            self.assertEqual(partial.read_bytes(), b'part')
            def complete(command, **_):
                self.assertEqual(command[command.index('-C') + 1], '-')
                partial.write_bytes(b'complete-model')
            with patch('captain_setup.subprocess.run', side_effect=complete) as run:
                download_artifact('https://example.org/model', target, checksum)
                download_artifact('https://example.org/model', target, checksum)
                run.assert_called_once()
            self.assertEqual(target.read_bytes(), b'complete-model')
            self.assertFalse(partial.exists())

    def test_completed_partial_promotes_offline_and_bad_hash_never_installs(self):
        from shared_llama import digest
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'model.gguf'
            partial = target.with_suffix('.gguf.download'); partial.write_bytes(b'complete')
            with patch('captain_setup.subprocess.run') as run:
                download_artifact('https://example.org/model', target, digest(partial))
                run.assert_not_called()
            target.unlink()
            partial.write_bytes(b'bad-data')
            with patch('captain_setup.subprocess.run'):
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    download_artifact('https://example.org/model', target, '0' * 64)
            self.assertFalse(target.exists())
            self.assertEqual(len(list(Path(folder).glob('*.invalid-*'))), 1)

    def test_interrupted_native_source_fetch_resumes_without_restoring_unused_models(self):
        import json
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'control').mkdir()
            config = self.config()
            path = root / 'control/config.json'; path.write_text(json.dumps(config))
            source = root / 'tools' / ('minicpm-llama-' + LLAMA_REVISION[:12])
            (source / '.git').mkdir(parents=True)  # Interrupted after git init.
            binary = source / 'build/bin/llama-server'
            binary.parent.mkdir(parents=True); binary.write_bytes(b'fixture executable')
            metadata, adapter = self.metadata()
            artifacts = select_artifacts(metadata, adapter)
            import hashlib
            for artifact in artifacts.values():
                artifact['sha256'] = hashlib.sha256(b'fixture weights').hexdigest()
            def run(command, **_):
                return CompletedProcess(command, 1 if '--verify' in command else 0)
            def download(url, destination, checksum):
                destination.write_bytes(b'fixture weights')
            with patch('common.port_open', return_value=False), patch('common.http', side_effect=[metadata, adapter]), \
                 patch('captain_setup.select_artifacts', return_value=artifacts), \
                 patch('captain_setup.build_tools', return_value='/cmake'), \
                 patch('captain_setup.subprocess.run', side_effect=run) as commands, \
                 patch('captain_setup.subprocess.check_output', side_effect=[LLAMA_REVISION, '']):
                installed = install_minicpm(root, download)
            self.assertTrue(any('fetch' in c.args[0] for c in commands.call_args_list))
            self.assertTrue(any('checkout' in c.args[0] for c in commands.call_args_list))
            self.assertEqual(installed['captain']['provider'], 'llama')
            self.assertEqual(installed['captain']['variant'], captain_setup.MODEL_VARIANT)
            self.assertIn('lora', installed['captain']['llama'])
            self.assertIn('AtomicChat', installed['text_models']['local-ai-captain']['model'])
            self.assertNotIn(config['model_team']['roles']['coder'], installed['text_models'])
            self.assertNotIn(config['model_team']['roles']['analyst'], installed['text_models'])
            self.assertEqual(json.loads((root / 'control/config.before-minicpm-captain.json').read_text()), config)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
