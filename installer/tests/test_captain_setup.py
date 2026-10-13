import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from captain_config import upgrade
from model_team import upgrade_team, team_roles
from text_models import upgrade_text_configuration
from captain_setup import configure, select_artifacts, build_tools
import work_agent
from common import ollama_environment


class CaptainSetupTests(unittest.TestCase):
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
            self.assertFalse(settings['tools']['team_run'])  # host policy enables after initialization

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
        metadata = {'sha': 'a' * 40, 'siblings': [
            {'rfilename': 'model-mix_q3gud_im.gguf', 'lfs': {'sha256': 'b' * 64}},
            {'rfilename': 'mmproj-model-f16.gguf', 'lfs': {'sha256': 'c' * 64}}]}
        artifacts = select_artifacts(metadata)
        self.assertIn('/resolve/' + 'a' * 40 + '/', artifacts['model']['url'])
        metadata['siblings'][0]['rfilename'] = 'model-mix_q3gud_im-les.gguf'
        with self.assertRaisesRegex(RuntimeError, 'layout changed'):
            select_artifacts(metadata)

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
            self.assertIn('cmake==3.31.8', installation)


if __name__ == '__main__':
    unittest.main()
