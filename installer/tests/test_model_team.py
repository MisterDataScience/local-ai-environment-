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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_team import upgrade_team, team_roles, PROFILES, QWEN4, CODER, REGISTRY_DIGESTS
from text_models import upgrade_text_configuration, configured_text_models, output_ceiling
from resource_modes import allowed
import work_agent
import team_setup


def config():
    return upgrade_team(upgrade_text_configuration({'api_key': 'local-only'}))


class TeamTests(unittest.TestCase):
    def test_native_shared_coder_enables_only_the_host_result_formatter(self):
        from captain_config import upgrade
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'control').mkdir()
            for name in ('opencode-team.mjs', 'captain.mjs', 'essay-edit-prompt.txt', 'reverse-scaffold-prompt.txt'):
                (root / 'control' / name).write_text('fixture')
            cfg = upgrade(config())
            cfg['captain'].update(provider='llama', single_model=True)
            cfg['text_models'][cfg['captain']['model_id']]['backend'] = 'llama'
            settings = work_agent.configuration(cfg, cfg['text_models'], root=root)
            self.assertTrue(settings['plugin'][0][1]['nativeStructuredResults'])
            for role in ('coder', 'coder-plan'):
                self.assertEqual(settings['agent'][role]['permission']['StructuredOutput'], 'allow')
                self.assertIn('calling StructuredOutput once', settings['agent'][role]['prompt'])
                self.assertNotIn('entire delegated reply must be one JSON object', settings['agent'][role]['prompt'])
                self.assertNotIn('Return exactly one JSON object', settings['agent'][role]['prompt'])
            self.assertEqual(settings['agent']['coder-plan']['permission']['*'], 'deny')
            self.assertNotIn('StructuredOutput', settings['agent']['analyst']['permission'])
            cfg['captain']['provider'] = 'ollama'
            cfg['text_models'][cfg['captain']['model_id']]['backend'] = 'ollama'
            settings = work_agent.configuration(cfg, cfg['text_models'], root=root)
            self.assertFalse(settings['plugin'][0][1]['nativeStructuredResults'])
            self.assertNotIn('StructuredOutput', settings['agent']['coder']['permission'])
            self.assertIn('entire delegated reply must be one JSON object', settings['agent']['coder']['prompt'])
            self.assertIn('Return exactly one JSON object', settings['agent']['coder-plan']['prompt'])

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
            for role in ('analyst', 'document', 'essay_document', 'scaffold_document'):
                agent = settings['agent'][role]
                self.assertEqual(agent['steps'], 2)
                self.assertLess(1, agent['steps'])  # First turn must avoid MAX_STEPS_PROMPT.
                self.assertEqual(agent['permission'], {'*': 'deny'})
            self.assertEqual(settings['agent']['coder']['steps'], 12)
            plan_coder = settings['agent']['coder-plan']
            self.assertEqual(plan_coder['mode'], 'subagent')
            self.assertTrue(plan_coder['hidden'])
            self.assertEqual(plan_coder['model'], settings['agent']['coder']['model'])
            self.assertEqual(plan_coder['permission'], {'*': 'deny',
                'read': {'*': 'allow', '*.env': 'deny', '*.env.*': 'deny'}, 'glob': 'allow', 'grep': 'allow'})
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
            for name in ('essay_document', 'scaffold_document'):
                self.assertEqual(settings['agent'][name]['mode'], 'subagent')
                self.assertTrue(settings['agent'][name]['hidden'])
                self.assertIn('\nMode: ', settings['agent'][name]['prompt'])
                self.assertEqual(settings['agent'][name]['model'], settings['agent']['document']['model'])
            for tool in ('edit', 'write', 'apply_patch'):
                self.assertEqual(settings['agent']['plan']['permission'][tool], 'deny')
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
        agents.append({'name': 'coder-plan', 'permission': [
            {'permission': '*', 'pattern': '*', 'action': 'deny'},
            *[{'permission': name, 'pattern': '*', 'action': 'allow'} for name in ('read', 'glob', 'grep')],
            {'permission': 'read', 'pattern': '*.env', 'action': 'deny'},
            {'permission': 'read', 'pattern': '*.env.*', 'action': 'deny'}]})
        response.read.return_value = json.dumps(agents).encode()
        with patch.object(team_setup, 'urlopen', return_value=response):
            from turnkey_install import ReadinessError
            with self.assertRaisesRegex(ReadinessError, 'policy did not load'):
                team_setup.verify_work_agent(Mock(poll=lambda: None), {'OPENCODE_SERVER_PASSWORD': 'local'}, True)
            for agent in agents[2:4]:
                agent['permission'].extend({'permission': 'task', 'pattern': r, 'action': 'allow'}
                                           for r in ('analyst', 'coder', 'coder-plan', 'document', 'essay_document', 'scaffold_document'))
                agent['permission'].extend({'permission': r, 'pattern': '*', 'action': 'ask'} for r in ('local_image', 'local_video', 'local_speech'))
            response.read.return_value = json.dumps(agents).encode()
            team_setup.verify_work_agent(Mock(poll=lambda: None), {'OPENCODE_SERVER_PASSWORD': 'local'}, True)
            # Native OpenCode appends plugin denials after the global deny.
            agents[0]['permission'].extend([
                {'permission': 'studio_contact', 'pattern': '*', 'action': 'deny'},
                {'permission': 'village_*', 'pattern': '*', 'action': 'deny'}])
            response.read.return_value = json.dumps(agents).encode()
            team_setup.verify_work_agent(Mock(poll=lambda: None), {'OPENCODE_SERVER_PASSWORD': 'local'}, True)
            for action in ('allow', 'ask'):
                agents[0]['permission'].append({'permission': 'village_*', 'pattern': '*', 'action': action})
                response.read.return_value = json.dumps(agents).encode()
                with self.assertRaisesRegex(ReadinessError, 'Specialist'):
                    team_setup.verify_work_agent(Mock(poll=lambda: None), {'OPENCODE_SERVER_PASSWORD': 'local'}, True)
                agents[0]['permission'].pop()
            agents[1]['permission'].append({'permission': 'edit', 'pattern': '*', 'action': 'allow'})
            response.read.return_value = json.dumps(agents).encode()
            with self.assertRaisesRegex(ReadinessError, 'approval permissions'):
                team_setup.verify_work_agent(Mock(poll=lambda: None), {'OPENCODE_SERVER_PASSWORD': 'local'}, True)

    def test_native_acceptance_requires_real_child_model_and_tool_result(self):
        for fault in (None, 'shared', 'native', 'native-schema-recovery', 'native-no-format', 'native-no-read',
                      'no-task', 'task-error', 'wrong-model', 'child-tool', 'coder-no-read'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                (root / 'control').mkdir()
                (root / 'logs').mkdir()
                (root / 'control/opencode-team.mjs').write_text('// test')
                (root / 'control/essay-edit-prompt.txt').write_text('Essay prompt')
                (root / 'control/reverse-scaffold-prompt.txt').write_text('Scaffold prompt')
                cfg = config()
                native_format = bool(fault and fault.startswith('native'))
                if fault == 'shared' or native_format:
                    from captain_config import upgrade
                    cfg = upgrade(cfg)
                    cfg['captain']['single_model'] = True
                    if native_format:
                        cfg['captain']['provider'] = 'llama'
                        cfg['text_models'][cfg['captain']['model_id']]['backend'] = 'llama'
                    (root / 'control/captain.mjs').write_text('// test')
                    for role in ('analyst', 'coder'):
                        del cfg['text_models'][cfg['model_team']['roles'][role]]
                expected_roles = team_roles(cfg, cfg['text_models'])
                if fault == 'native-schema-recovery':
                    from test_native_session_store import create_history
                    database = root / 'work-agent/state/data/opencode/opencode.db'
                    database.parent.mkdir(parents=True)
                    create_history(database, parent_id='2', call_id='actual-native-task',
                        model_id=expected_roles['coder'], task_status='completed', read_status='completed', final=True)
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
                            if fault == 'native-schema-recovery' and role == 'coder':
                                from urllib.error import HTTPError
                                raise HTTPError(url, 400, 'Bad request', {},
                                    io.BytesIO(json.dumps({'data': {'message': 'Expected OutputFormatJsonSchema'}}).encode()))
                            use_format = native_format and role == 'coder' and fault != 'native-no-format'
                            result = [{'info': {'role': 'assistant', 'providerID': 'local-ai-gateway',
                                'modelID': 'wrong' if fault == 'wrong-model' else expected_roles[role],
                                **({'structured': {'summary': 'Fixture result'}} if use_format else {})},
                                'parts': ([] if use_format else [{'type': 'text', 'text': 'Result'}]) +
                                         ([{'type': 'tool', 'tool': 'StructuredOutput', 'state': {'status': 'completed'}}]
                                          if use_format else []) +
                                         ([{'type': 'tool', 'tool': 'bash'}] if fault == 'child-tool' else
                                          [{'type': 'tool', 'tool': 'read', 'state': {'status': 'completed'}}]
                                          if role == 'coder' and fault not in ('coder-no-read', 'native-no-read') else [])}]
                        else:
                            result = [] if fault == 'no-task' else [{'parts': [{'type': 'tool', 'tool': 'task',
                                'callID': 'actual-native-task',
                                'state': {'status': 'error' if fault == 'task-error' else 'completed',
                                          **({'error': 'SchemaError(Expected OutputFormatJsonSchema)'} if fault == 'task-error' else {}),
                                          'input': {'subagent_type': 'coder-plan' if role == 'coder' else role},
                                          'metadata': {'sessionId': 'child', 'localTeamReview': 'ready_for_review'}}}]}]
                    return io.BytesIO(json.dumps(result).encode())
                status = {'mode': 'max', 'instance_id': 'backend', 'epoch': 0}
                with patch('common.http', side_effect=[status, {'data': [{'id': k} for k in cfg['text_models']]}]), \
                     patch.object(team_setup, 'port_open', return_value=False), \
                     patch.object(team_setup, 'verify_work_agent'), \
                     patch.object(team_setup.subprocess, 'Popen', return_value=Mock()), \
                     patch.object(team_setup, 'stop_process') as stop, \
                     patch.object(team_setup, 'urlopen', side_effect=native):
                    if fault and fault not in ('shared', 'native', 'native-schema-recovery'):
                        with self.assertRaises(team_setup.ReadinessError) as raised:
                            team_setup.verify_native_handoffs(root, cfg)
                        if fault in ('no-task', 'task-error'):
                            diagnostic = root / 'logs/native-acceptance/opencode-handoff-analyst-failure.json'
                            saved = json.loads(diagnostic.read_text())
                            self.assertEqual(saved['task_count'], 0 if fault == 'no-task' else 1)
                            self.assertIn('diagnostic=' + str(diagnostic), str(raised.exception))
                            if fault == 'task-error':
                                self.assertIn('SchemaError(Expected OutputFormatJsonSchema)', str(raised.exception))
                                self.assertEqual(saved['tasks'][0]['call_id'], 'actual-native-task')
                    else:
                        checks = team_setup.verify_native_handoffs(root, cfg)
                        self.assertEqual(len(checks), 2)
                        if fault == 'native-schema-recovery':
                            self.assertEqual(checks[1]['history_source'], 'native_sqlite_readonly')
                    stop.assert_called_once()


if __name__ == '__main__': unittest.main()
