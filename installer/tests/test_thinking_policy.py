"""Thinking defaults, migration and per-role inheritance."""
import copy
from pathlib import Path
import tempfile
import unittest

from text_models import DEFAULT_TEXT_MODELS, configured_text_models, upgrade_text_configuration
from model_team import upgrade_team
from captain_config import upgrade
import work_agent


class ThinkingPolicyTests(unittest.TestCase):
    def test_existing_profiles_are_enabled_once_without_losing_customisation(self):
        config = {'thinking': False, 'api_key': 'local-only', 'text_models': copy.deepcopy(DEFAULT_TEXT_MODELS)}
        for preset in config['text_models'].values():
            preset['thinking'] = False
        config['text_models']['local-ai-large'].update(model='custom:7b', num_ctx=4096)
        original = copy.deepcopy(config)
        upgraded = upgrade_text_configuration(config)
        self.assertEqual(config, original)
        self.assertTrue(upgraded['thinking'])
        self.assertTrue(all(p['thinking'] for p in upgraded['text_models'].values()))
        self.assertEqual(upgraded['text_models']['local-ai-large']['model'], 'custom:7b')
        self.assertEqual(upgraded['text_models']['local-ai-large']['num_ctx'], 4096)
        self.assertEqual(upgrade_text_configuration(upgraded), upgraded)

    def test_fresh_stock_and_team_presets_all_enable_thinking(self):
        self.assertTrue(all(p['thinking'] for p in DEFAULT_TEXT_MODELS.values()))
        config = upgrade_team(upgrade_text_configuration({}))
        self.assertTrue(all(p['thinking'] for p in configured_text_models(config).values()))

    def test_every_native_agent_inherits_a_thinking_enabled_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = root / 'control'; control.mkdir()
            for name in ('opencode-team.mjs', 'captain.mjs', 'essay-edit-prompt.txt', 'reverse-scaffold-prompt.txt'):
                (control / name).write_text('fixture')
            config = upgrade(upgrade_team(upgrade_text_configuration({'api_key': 'test'})))
            config['captain']['single_model'] = True
            settings = work_agent.configuration(config, list(config['text_models']), root=root,
                status={'instance_id':'test', 'epoch':0, 'mode':'normal'})
            checked = set()
            for name, agent in settings['agent'].items():
                if agent.get('disable') or 'model' not in agent:
                    continue
                identifier = agent['model'].split('/', 1)[1]
                self.assertTrue(config['text_models'][identifier]['thinking'], name)
                checked.add(name)
            self.assertTrue({'plan', 'build', 'analyst', 'coder', 'coder-plan', 'document',
                'essay_document', 'scaffold_document', 'captain-researcher', 'captain-analyst',
                'captain-coder', 'captain-writer', 'captain-reviewer'}.issubset(checked))
