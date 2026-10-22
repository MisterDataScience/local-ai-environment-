import copy
import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'payload'))
from model_team import upgrade_team, team_roles, PROFILES, QWEN4, CODER, REGISTRY_DIGESTS
from text_models import upgrade_text_configuration, configured_text_models, output_ceiling
from resource_modes import allowed
import work_agent
import team_setup


def config():
    return upgrade_team(upgrade_text_configuration({'api_key': 'local-only'}))


class TeamTests(unittest.TestCase):
    def test_stock_upgrade_and_custom_preservation(self):
        original = upgrade_text_configuration({'api_key': 'secret', 'vault': {'enabled': False}})
        old = copy.deepcopy(original)
        upgraded = upgrade_team(original)
        self.assertEqual(original, old)
        self.assertEqual(upgraded['api_key'], 'secret')
        self.assertEqual(upgraded['vault'], old['vault'])
        self.assertEqual(upgrade_team(upgraded), upgraded)
        for role, identifier in upgraded['model_team']['roles'].items():
            self.assertEqual(upgraded['text_models'][identifier]['num_ctx'], PROFILES[role][1])
        original['text_models']['local-ai']['model'] = 'custom:7b'
        original['text_models']['local-ai']['num_ctx'] = 4096
        original['text_models']['local-ai-large']['keep_alive_seconds'] = 45
        upgraded = upgrade_team(original)
        self.assertEqual(upgraded['text_models']['local-ai'], original['text_models']['local-ai'])
        self.assertEqual(upgraded['model_team']['roles']['coordinator'], 'local-ai-team-coordinator')
        self.assertEqual(upgraded['text_models']['local-ai-large']['keep_alive_seconds'], 45)

    def test_roles_contexts_and_gaming_are_enforced(self):
        cfg = config()
        for identifier, preset in configured_text_models(cfg).items():
            self.assertTrue(allowed('normal', identifier, preset))
            self.assertEqual(allowed('gaming', identifier, preset), preset['role'] == 'coordinator')
            self.assertFalse(allowed('gaming', identifier, preset, 'image'))
            self.assertFalse(allowed('normal', identifier, preset, 'video'))
            self.assertEqual(output_ceiling('gaming', preset), 1024)
        coordinator = cfg['text_models'][cfg['model_team']['roles']['coordinator']]
        self.assertEqual(output_ceiling('max', coordinator), 4096)
        coordinator['model'] = 'unknown:100b'
        with self.assertRaises(ValueError): configured_text_models(cfg)
        cfg = config()
        cfg['text_models']['local-ai']['num_ctx'] = 8193
        with self.assertRaises(ValueError): configured_text_models(cfg)

    def test_custom_context_and_disabled_team_survive_reinstallation(self):
        cfg = config()
        cfg['model_team']['enabled'] = False
        cfg['text_models']['local-ai']['num_ctx'] = 4096
        self.assertEqual(upgrade_team(upgrade_text_configuration(cfg)), cfg)
        self.assertEqual(team_roles(cfg, cfg['text_models']), {})

    def test_opencode_roles_and_failure_closed_configuration(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'control').mkdir()
            cfg = config()
            with self.assertRaises(RuntimeError):
                work_agent.configuration(cfg, cfg['text_models'], root=root)
            (root / 'control/opencode-team.mjs').write_text('// test')
            (root / 'control/essay-edit-prompt.txt').write_text('Essay prompt')
            (root / 'control/reverse-scaffold-prompt.txt').write_text('Scaffold prompt')
            settings = work_agent.configuration(cfg, cfg['text_models'], root=root)
            from common import GLOBAL_BEHAVIOUR
            for name in ('plan', 'build', 'analyst', 'coder', 'document'):
                self.assertTrue(settings['agent'][name]['prompt'].startswith(GLOBAL_BEHAVIOUR + '\n'))
            self.assertTrue(settings['agent']['general']['disable'])
            self.assertNotIn('prompt', settings['agent']['general'])
            self.assertTrue(settings['agent']['explore']['disable'])
            self.assertEqual(settings['agent']['build']['permission']['task'], 'deny')
            self.assertFalse(settings['tools']['task'])
            self.assertEqual(settings['agent']['analyst']['permission'], {'*': 'deny'})
            self.assertEqual(settings['agent']['coder']['steps'], 12)
            self.assertEqual(settings['agent']['coder']['permission']['edit'], 'ask')
            self.assertEqual(settings['agent']['coder']['permission']['bash'], 'ask')
            self.assertEqual(settings['agent']['coder']['permission']['task'], 'deny')
            self.assertEqual(settings['subagent_depth'], 1)
            self.assertFalse(settings['command']['code']['subtask'])
            self.assertEqual(settings['agent']['document']['permission'], {'*':'deny'})
            self.assertEqual(settings['agent']['document']['mode'], 'all')
            self.assertNotIn('Essay prompt', settings['agent']['document']['prompt'])
            self.assertNotIn('Scaffold prompt', settings['agent']['document']['prompt'])
            self.assertIn('Essay prompt', settings['agent']['essay_document']['prompt'])
            self.assertNotIn('Scaffold prompt', settings['agent']['essay_document']['prompt'])
            self.assertIn('Scaffold prompt', settings['agent']['scaffold_document']['prompt'])
            self.assertNotIn('Essay prompt', settings['agent']['scaffold_document']['prompt'])
            self.assertEqual(settings['agent']['essay_document']['permission'], {'*':'deny'})
            self.assertEqual(settings['agent']['scaffold_document']['permission'], {'*':'deny'})
            self.assertNotIn('essay-edit', settings['command'])
            self.assertEqual(settings['provider']['local-ai-gateway']['models']['local-ai-large']['limit']['context'], 32768)
            work_agent.environment(root, cfg, settings)
            ledger = root / 'work-agent/state/team-budget.json'
            self.assertEqual(ledger.stat().st_mode & 0o777, 0o600)
            ledger.write_text('{"version":1,"turns":{"preserved":true}}')
            work_agent.environment(root, cfg, settings)
            self.assertIn('preserved', ledger.read_text())

    def test_preparation_pins_artifacts_and_refuses_moved_tag(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'control').mkdir()
            models = config()['text_models']
            def http(url, body=None):
                if url.endswith('/api/tags'):
                    return {'models': [{'name': m, 'digest': REGISTRY_DIGESTS.get(m, 'c' * 64).ljust(64, '0')}
                                       for m in {p['model'] for p in models.values()}]}
                return {'details': {'family': 'gemma4' if body['model'] == CODER else 'qwen35',
                                    'quantization_level': 'Q4_K_M'}, 'capabilities': ['tools']}
            download, run = Mock(), Mock()
            team_setup.prepare_models(root, models, download, run, http)
            self.assertEqual(download.call_count, 1)
            self.assertEqual(len(download.call_args.args[2]), 64)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(len(json.loads((root / 'control/model-artifacts.json').read_text())), 3)
            moved = lambda url, body=None: {'models': [{'name': QWEN4, 'digest': 'f' * 64}]}
            with self.assertRaisesRegex(RuntimeError, 'tag changed'):
                team_setup.prepare_models(root, models, download, run, moved)

    def test_startup_checks_effective_permissions(self):
        agents = [{'name': r, 'permission': [{'permission': '*', 'pattern': '*', 'action': 'deny'},
                   {'permission': 'external_directory', 'pattern': '/tool-output/*', 'action': 'allow'}]}
                  for r in ('analyst', 'coder')]
        agents += [{'name': r, 'permission': [{'permission': 'task', 'pattern': '*', 'action': 'deny'}]}
                   for r in ('plan', 'build')]
        agents[1]['steps'] = 12
        agents[1]['permission'] = [{'permission': '*', 'pattern': '*', 'action': 'deny'}] + [
            {'permission': name, 'pattern': pattern, 'action': action} for name, pattern, action in (
                ('read', '*', 'allow'), ('read', '*.env', 'deny'), ('glob', '*', 'allow'),
                ('grep', '*', 'allow'), ('edit', '*', 'ask'), ('bash', '*', 'ask'))]
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        agents.extend({'name': name, 'permission': [{'permission': '*', 'pattern': '*', 'action': 'deny'}]}
                      for name in ('document', 'essay_document', 'scaffold_document'))
        response.read.return_value = json.dumps(agents).encode()
        with patch.object(team_setup, 'urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'policy did not load'):
                team_setup.verify_work_agent(Mock(poll=lambda: None), {'OPENCODE_SERVER_PASSWORD': 'local'}, True)
            for agent in agents[2:4]:
                agent['permission'].extend({'permission': 'task', 'pattern': r, 'action': 'allow'}
                                           for r in ('analyst', 'coder', 'document', 'essay_document', 'scaffold_document'))
                agent['permission'].extend({'permission': r, 'pattern': '*', 'action': 'ask'} for r in ('local_image', 'local_video', 'local_speech'))
            response.read.return_value = json.dumps(agents).encode()
            team_setup.verify_work_agent(Mock(poll=lambda: None), {'OPENCODE_SERVER_PASSWORD': 'local'}, True)
            agents[1]['permission'].append({'permission': 'edit', 'pattern': '*', 'action': 'allow'})
            response.read.return_value = json.dumps(agents).encode()
            with self.assertRaisesRegex(RuntimeError, 'approval permissions'):
                team_setup.verify_work_agent(Mock(poll=lambda: None), {'OPENCODE_SERVER_PASSWORD': 'local'}, True)

    def test_native_acceptance_requires_real_child_model_and_tool_result(self):
        for fault in (None, 'shared', 'no-task', 'wrong-model', 'child-tool', 'coder-no-read'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                (root / 'control').mkdir()
                (root / 'logs').mkdir()
                (root / 'control/opencode-team.mjs').write_text('// test')
                (root / 'control/essay-edit-prompt.txt').write_text('Essay prompt')
                (root / 'control/reverse-scaffold-prompt.txt').write_text('Scaffold prompt')
                cfg = config()
                if fault == 'shared':
                    from captain_config import upgrade
                    cfg = upgrade(cfg)
                    cfg['captain']['single_model'] = True
                    (root / 'control/captain.mjs').write_text('// test')
                    for role in ('analyst', 'coder'):
                        del cfg['text_models'][cfg['model_team']['roles'][role]]
                expected_roles = team_roles(cfg, cfg['text_models'])
                state = {'number': 0}
                def native(request, **kwargs):
                    url = request.full_url
                    if url.endswith('/session'):
                        state['number'] += 1
                        result = {'id': str(state['number'])}
                    elif request.data is not None:
                        result = {'info': {}, 'parts': [{'type': 'text', 'text': 'Final answer'}]}
                    else:
                        role = 'analyst' if state['number'] == 1 else 'coder'
                        if '/child/' in url:
                            result = [{'info': {'role': 'assistant', 'providerID': 'local-ai-gateway',
                                'modelID': 'wrong' if fault == 'wrong-model' else expected_roles[role]},
                                'parts': [{'type': 'text', 'text': 'Result'}] +
                                         ([{'type': 'tool', 'tool': 'bash'}] if fault == 'child-tool' else
                                          [{'type': 'tool', 'tool': 'read', 'state': {'status': 'completed'}}]
                                          if role == 'coder' and fault != 'coder-no-read' else [])}]
                        else:
                            result = [] if fault == 'no-task' else [{'parts': [{'type': 'tool', 'tool': 'task',
                                'state': {'status': 'completed', 'input': {'subagent_type': role},
                                          'metadata': {'sessionId': 'child', 'localTeamReview': 'ready_for_review'}}}]}]
                    return io.BytesIO(json.dumps(result).encode())
                status = {'mode': 'max', 'instance_id': 'backend', 'epoch': 0}
                with patch('common.http', side_effect=[status, {'data': [{'id': k} for k in cfg['text_models']]}]), \
                     patch.object(team_setup, 'port_open', return_value=False), \
                     patch.object(team_setup, 'verify_work_agent'), \
                     patch.object(team_setup.subprocess, 'Popen', return_value=Mock()), \
                     patch.object(team_setup, 'stop_process') as stop, \
                     patch.object(team_setup, 'urlopen', side_effect=native):
                    if fault and fault != 'shared':
                        with self.assertRaises(RuntimeError): team_setup.verify_native_handoffs(root, cfg)
                    else:
                        self.assertEqual(len(team_setup.verify_native_handoffs(root, cfg)), 2)
                    stop.assert_called_once()


if __name__ == '__main__': unittest.main()
