"""Regression coverage for integrated workflows and audited scheduler failures."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
import scheduled_tasks as tasks
import work_agent
from model_engine import Engine
from model_team import preset


class ScheduledSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'control/scheduled-tasks').mkdir(parents=True)
        self.config = {'api_key': 'fixture', 'text_models': {'local-ai': preset('coordinator')}}
        (self.root / 'control/config.json').write_text(json.dumps(self.config))
        self.engine = Engine(self.config, self.root / 'control')
        self.engine.mode = 'max'
        self.addCleanup(self.engine.executor.shutdown)

    def task(self, prompt):
        task = {'id': 'a' * 32, 'prompt': prompt, 'model': 'local-ai',
                'schedule': {'interval': 900}, 'authorized': True}
        tasks.atomic_json(self.root / 'control/scheduled-tasks' / (task['id'] + '.json'), task)
        return task

    def test_scheduled_commands_are_rejected_before_any_backend_or_output(self):
        for command in ('image', 'video', 'search', 'read', 'reverse', 'speak'):
            for prompt in ('/' + command + ' fixture', '\t/' + command.upper() + '\nfixture'):
                with self.subTest(prompt=prompt):
                    task = self.task(prompt)
                    status_path = self.root / 'control/scheduled-tasks' / (task['id'] + '.status.json')
                    status_path.unlink(missing_ok=True)
                    def backend(url, payload=None, **kwargs):
                        if url.endswith('/control/mode'):
                            return {'mode': 'max', 'transitioning': False, 'error': None}
                        self.assertTrue(payload['inference_only'])
                        self.engine.submit(payload).result(1)
                        self.fail('Command was admitted')
                    with patch.object(tasks, 'http', side_effect=backend), patch('model_engine.api') as api:
                        result = tasks.run_task(self.root, task['id'])
                    self.assertEqual(result['status'], 'blocked-or-failed')
                    api.assert_not_called()
                    self.assertFalse((self.root / 'work-agent/scheduled-outputs').exists())

    def test_cutoff_is_saved_as_incomplete_and_never_retried_in_same_slot(self):
        task = self.task('Write a fixture report.')
        calls = []
        def backend(url, payload=None, **kwargs):
            calls.append(url)
            if url.endswith('/control/mode'):
                return {'mode': 'normal', 'transitioning': False, 'error': None}
            return {'choices': [{'message': {'content': 'Partial report'}, 'finish_reason': 'length'}]}
        now = dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc)
        with patch.object(tasks, 'http', side_effect=backend):
            first = tasks.run_task(self.root, task['id'], now)
            second = tasks.run_task(self.root, task['id'], now)
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'incomplete')
        self.assertEqual(first['finish_reason'], 'length')
        self.assertEqual(Path(first['output']).read_text(), 'Partial report')
        self.assertEqual(len(calls), 2)


class CombinedLauncherTests(unittest.TestCase):
    def test_scoped_profile_disables_new_file_vision_and_pdf_connections(self):
        for scoped in (False, True):
            with self.subTest(scoped=scoped), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'control').mkdir()
                (root / 'control/automation-guard.mjs').write_text('// fixture')
                config = {'api_key': 'fixture', 'text_models': {'local-ai': preset('coordinator')},
                          'desktop': {'enabled': scoped}}
                (root / 'control/config.json').write_text(json.dumps(config))
                binary = root / 'tools/opencode' / work_agent.VERSION / 'opencode'
                binary.parent.mkdir(parents=True)
                binary.write_text('fixture')
                process = Mock()
                process.pid = os.getpid()
                process.poll.return_value = None
                responses = [{'mode': 'normal', 'transitioning': False, 'error': None},
                             {'data': [{'id': 'local-ai'}]},
                             {'mode': 'gaming', 'transitioning': False, 'error': None}]
                with patch.object(sys, 'argv', ['work_agent', '--root', directory]), \
                     patch('builtins.input', return_value=''), patch('builtins.print'), \
                     patch.object(work_agent, 'http', side_effect=responses), \
                     patch.object(work_agent, 'port_open', return_value=False), \
                     patch.object(work_agent.subprocess, 'run'), \
                     patch.object(work_agent.subprocess, 'Popen', return_value=process) as launch, \
                     patch.object(work_agent, 'stop_process'), patch.object(work_agent.time, 'sleep'), \
                     patch('automation_setup.verify_connection') as verify_scoped, \
                     patch('required_tools_setup.verify') as verify_required, \
                     patch('file_workflows.publish_project') as publish:
                    work_agent.main()
                settings = json.loads(launch.call_args.kwargs['env']['OPENCODE_CONFIG_CONTENT'])
                for name in ('projectfiles', 'projectpdf', 'projectvision'):
                    self.assertEqual(settings['mcp'][name]['enabled'], not scoped)
                if scoped:
                    verify_scoped.assert_called_once()
                    verify_required.assert_not_called()
                    publish.assert_not_called()
                    self.assertEqual(settings['agent']['build']['permission']['*'], 'deny')
                else:
                    verify_scoped.assert_not_called()
                    verify_required.assert_called_once()
                    publish.assert_called_once()


if __name__ == '__main__':
    unittest.main()
