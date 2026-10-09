"""Integration regressions across owned uploads, live HTTP, MCP and scheduling."""
import asyncio
import base64
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'payload'))
from PIL import Image
import chat_attachments as attachments
import file_workflows
import scheduled_tasks as tasks
from file_transfer import transfer_local
from http_api import Handler
from model_engine import Engine
from model_team import preset
from tool_protocol import messages_for_ollama
from pdf_mcp import dispatch as pdf_dispatch
import service_lifecycle
import webui_local_images


def image_bytes():
    output = io.BytesIO()
    Image.new('RGB', (80, 60), 'red').save(output, format='PNG')
    return output.getvalue()


class CapabilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.uploads = self.root / 'webui/data/uploads'
        self.uploads.mkdir(parents=True)
        self.project = self.root / 'work-agent/projects' / ('a' * 32)
        self.project.mkdir(parents=True)
        (self.root / 'control').mkdir()
        self.config = {'api_key': 'test-key', 'text_models': {'local-ai': preset('coordinator')}}
        (self.root / 'control/config.json').write_text(json.dumps(self.config))

    def record(self, suffix, content, owner='owner'):
        path = self.uploads / ('uploaded' + suffix)
        path.write_bytes(content)
        return SimpleNamespace(id='test-upload', user_id=owner, path=str(path), filename='original' + suffix)

    def inlet(self, record, body):
        async def lookup(identifier):
            return record if identifier == record.id else None
        return asyncio.run(attachments.inlet(body, {'id': 'owner'}, self.root, self.uploads, lookup))

    def test_native_upload_reference_becomes_pixels_and_approved_project_copy(self):
        record = self.record('.png', image_bytes())
        body = {'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Describe it'}, {'type': 'image_url', 'image_url': {'url': '/api/v1/files/test-upload/content'}}]}],
            'files': [{'type': 'image', 'id': record.id}]}
        result = self.inlet(record, body)
        messages = messages_for_ollama(result['messages'])
        self.assertEqual(len(messages[0]['images']), 1)
        self.assertIn('test-upload/attachment.png', messages[0]['content'])
        copied = transfer_local(self.root, self.project.name, 'test-upload/attachment.png', 'chat-import')
        self.assertEqual(copied.read_bytes(), image_bytes())
        with self.assertRaises(FileExistsError):
            transfer_local(self.root, self.project.name, 'test-upload/attachment.png', 'chat-import')
        ledger = (self.root / 'work-agent/state/transfers.jsonl').read_text()
        self.assertIn('completed', ledger)
        self.assertNotIn('Describe it', ledger)

    def test_upload_ownership_and_external_image_fail_before_extraction(self):
        record = self.record('.pdf', b'%PDF-fake', owner='someone-else')
        with patch.object(attachments, 'read_pdf') as extract:
            with self.assertRaises(ValueError):
                self.inlet(record, {'messages': [{'role': 'user', 'content': 'Read this'}], 'files': [{'id': record.id}]})
            extract.assert_not_called()
        with self.assertRaises(ValueError):
            self.inlet(record, {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.org/picture.png'}}]}]})

    def test_changed_upload_does_not_reuse_stale_staged_evidence(self):
        record = self.record('.txt', b'Original evidence')
        attachments.stage(self.root, record, self.uploads, 'owner')
        Path(record.path).write_text('Changed evidence')
        with self.assertRaises(ValueError):
            attachments.stage(self.root, record, self.uploads, 'owner')

    def test_scanned_chat_pdf_injects_page_evidence_and_keeps_continuation(self):
        record = self.record('.pdf', b'%PDF-fake')
        evidence = {'page_count': 9, 'pages': [{'page': 1, 'text': 'SCANNED SAMPLE', 'method': 'ocr', 'truncated': False}], 'limited': True, 'next_page': 5}
        body = {'messages': [{'role': 'user', 'content': 'Summarise'}], 'files': [{'type': 'file', 'id': record.id}]}
        with patch.object(attachments, 'read_pdf', return_value=evidence):
            result = self.inlet(record, body)
        self.assertIn('SCANNED SAMPLE', result['messages'][0]['content'])
        self.assertIn('"next_page": 5', result['messages'][0]['content'])
        self.assertEqual(result['files'], [])
        with patch('file_workflows.read_pdf', return_value=evidence) as read:
            file_workflows.execute(self.root, {}, 'read_attachment_pdf', {'path': 'test-upload/attachment.pdf', 'start_page': 5})
            self.assertEqual(read.call_args.kwargs['start_page'], 5)

    def test_live_gateway_workflow_authentication_and_project_handoff(self):
        file_workflows.publish_project(self.root, self.project, os.getpid())
        browser = self.root / 'web/browser-outputs'
        browser.mkdir(parents=True)
        (browser / 'report.csv').write_text('A,B\n1,2\n')
        engine = SimpleNamespace(root=self.root / 'control', config=self.config)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.engine = engine
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = 'http://127.0.0.1:' + str(server.server_port)
            with self.assertRaises(HTTPError) as denied:
                urlopen(base + '/files/openapi.json')
            self.assertEqual(denied.exception.code, 401)
            headers = {'Authorization': 'Bearer test-key', 'Content-Type': 'application/json'}
            spec = json.load(urlopen(Request(base + '/files/openapi.json', headers=headers)))
            self.assertIn('/files/transfer_workflow_file', spec['paths'])
            request = Request(base + '/files/transfer_workflow_file', data=json.dumps({'direction': 'browser-import', 'path': 'report.csv'}).encode(), headers=headers)
            response = json.load(urlopen(request))
            self.assertTrue(Path(response['saved']).is_file())
            self.assertEqual((self.project / 'Inbox/report.csv').read_text(), 'A,B\n1,2\n')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_symlink_ancestor_and_absent_active_agent_never_transfer(self):
        browser = self.root / 'web/browser-outputs'
        browser.mkdir(parents=True)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'secret.txt').write_text('private')
        (browser / 'linked').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            transfer_local(self.root, self.project.name, 'linked/secret.txt', 'browser-import')
        with self.assertRaises(OSError):
            file_workflows.execute(self.root, {}, 'transfer_workflow_file', {'direction': 'browser-import', 'path': 'report.csv'})

    def test_real_stdio_mcp_discovers_pdf_transfer_and_vision(self):
        for module, extra, expected in [('pdf_mcp.py', [], 'read_pdf'),
            ('transfer_mcp.py', ['--root', str(self.root)], 'transfer_file'),
            ('vision_mcp.py', ['--root', str(self.root)], 'inspect_image')]:
            request = '\n'.join(json.dumps(m) for m in [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}]) + '\n'
            process = subprocess.run([sys.executable, str(ROOT / module), '--project', str(self.project), *extra],
                input=request, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            responses = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual([r['id'] for r in responses], [1, 2])
            self.assertIn(expected, [tool['name'] for tool in responses[-1]['result']['tools']])

    def task(self):
        task = {'id': 'b' * 32, 'prompt': 'Write a short checklist', 'model': 'local-ai', 'schedule': {'interval': 3600}, 'authorized': True}
        tasks.atomic_json(self.root / 'control/scheduled-tasks' / (task['id'] + '.json'), task)
        return task

    def test_authorized_schedule_runs_once_and_never_supplies_tools(self):
        task = self.task()
        now = dt.datetime(2026, 10, 9, 12, tzinfo=dt.timezone.utc)
        calls = []
        def backend(url, payload=None, **kwargs):
            calls.append((url, payload))
            if url.endswith('/control/mode'):
                return {'mode': 'normal', 'transitioning': False, 'error': None}
            return {'choices': [{'message': {'content': 'Checklist output'}}]}
        with patch.object(tasks, 'http', side_effect=backend):
            first = tasks.run_task(self.root, task['id'], now)
            second = tasks.run_task(self.root, task['id'], now)
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1][1]['tool_choice'], 'none')
        self.assertNotIn('tools', calls[-1][1])
        self.assertEqual(Path(first['output']).read_text(), 'Checklist output')

    def test_gaming_and_locked_vault_block_scheduled_inference_and_plaintext_outputs(self):
        task = self.task()
        with patch.object(tasks, 'http', return_value={'mode': 'gaming', 'transitioning': False, 'error': None}) as backend:
            self.assertEqual(tasks.run_task(self.root, task['id'])['status'], 'blocked-or-failed')
            self.assertEqual(backend.call_count, 1)
        (self.root / 'control/scheduled-tasks' / (task['id'] + '.status.json')).unlink()
        self.config['vault'] = {'enabled': True}
        (self.root / 'control/config.json').write_text(json.dumps(self.config))
        with patch.object(tasks, 'http', return_value={'mode': 'normal', 'transitioning': False, 'error': None}) as backend:
            self.assertEqual(tasks.run_task(self.root, task['id'])['status'], 'blocked-or-failed')
            self.assertEqual(backend.call_count, 1)
        self.assertFalse((self.root / 'work-agent/scheduled-outputs').exists())

    def test_invalid_authorization_and_launchd_job_have_no_shell_or_keepalive(self):
        task = self.task()
        plist = tasks.launch_agent(self.root, task)
        self.assertEqual(plist['StartInterval'], 3600)
        self.assertNotIn('KeepAlive', plist)
        self.assertNotIn('RunAtLoad', plist)
        self.assertNotIn('/bin/sh', plist['ProgramArguments'])
        task['authorized'] = False
        with self.assertRaises(ValueError):
            tasks.validate(task)

    def test_tool_image_result_preserves_pairing_and_pixel_data(self):
        image = 'data:image/png;base64,' + base64.b64encode(image_bytes()).decode()
        messages = messages_for_ollama([
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'call1', 'function': {'name': 'browser_screenshot', 'arguments': {}}}]},
            {'role': 'tool', 'tool_call_id': 'call1', 'content': [{'type': 'text', 'text': 'Screenshot'}, {'type': 'image_url', 'image_url': {'url': image}}]}])
        self.assertEqual(messages[-1]['tool_name'], 'browser_screenshot')
        self.assertEqual(len(messages[-1]['images']), 1)

    def test_vision_unsupported_artifact_and_gaming_fail_without_inference(self):
        body = {'model': 'local-ai', 'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(image_bytes()).decode()}}]}]}
        engine = Engine(self.config, self.root / 'control')
        self.addCleanup(engine.executor.shutdown)
        engine.mode = 'gaming'
        with self.assertRaises(ValueError):
            engine.check_policy({'model': 'local-ai', '_vision': True}, 'text')
        with patch('model_engine.api') as backend:
            with self.assertRaises(ValueError):
                engine.submit(body)
            backend.assert_not_called()
        engine.mode = 'normal'
        with patch('model_engine.api', return_value={'models': [], 'capabilities': ['completion']}) as backend, patch.object(engine, 'stop_comfy'), patch('model_engine.port_open', return_value=False):
            with self.assertRaises(ValueError):
                engine.submit(body).result(3)
            self.assertNotIn('/api/chat', [call.args[1] for call in backend.call_args_list])

    def test_pdf_subprocess_timeout_is_reported_as_tool_error(self):
        with patch('pdf_mcp.read_pdf', side_effect=RuntimeError('PDF extraction timed out')):
            response = pdf_dispatch({'id': 1, 'method': 'tools/call', 'params': {'name': 'read_pdf', 'arguments': {'path': 'report.pdf', 'start_page': 5}}}, self.project)
        self.assertTrue(response['result']['isError'])

    def test_orphan_recovery_refuses_reused_pid(self):
        tasks.atomic_json(self.root / 'control/runtime-services.json', {'services': [{'pid': 12345, 'identity': str(self.root) + '/old-service'}]})
        with patch.object(service_lifecycle, 'fingerprint', return_value='unrelated-service'), patch.object(service_lifecycle.os, 'killpg') as kill:
            service_lifecycle.recover(self.root)
            kill.assert_not_called()

    def test_explicit_stop_unloads_only_this_installation_login_job(self):
        import plistlib
        import signal
        from login_startup import LABEL
        identity = str(self.root / 'control/runtime.py')
        tasks.atomic_json(self.root / 'control/runtime-owner.json', {'pid': 12345, 'identity': identity})
        home = self.root / 'test-home'
        agent = home / 'Library/LaunchAgents' / (LABEL + '.plist')
        agent.parent.mkdir(parents=True)
        for owner, should_unload in [(self.root, True), (self.root / 'unrelated-installation', False)]:
            agent.write_bytes(plistlib.dumps({'Label': LABEL, 'ProgramArguments': [str(owner / 'control/.venv/bin/python'), str(owner / 'control/runtime.py'), '--background']}))
            with patch.object(service_lifecycle.Path, 'home', return_value=home), patch.object(service_lifecycle, 'fingerprint', return_value=identity), patch.object(service_lifecycle.subprocess, 'run') as launchctl, patch.object(service_lifecycle.os, 'kill') as kill, patch('builtins.print'):
                service_lifecycle.stop(self.root)
                self.assertEqual(launchctl.called, should_unload)
                if should_unload:
                    self.assertEqual(launchctl.call_args.args[0][:2], ['/bin/launchctl', 'bootout'])
                kill.assert_called_once_with(12345, signal.SIGTERM)
            self.assertTrue(agent.exists())

    def test_pinned_native_webui_image_fetch_patch_is_verified_and_idempotent(self):
        import importlib.metadata
        try:
            distribution = importlib.metadata.distribution('open-webui')
        except importlib.metadata.PackageNotFoundError:
            self.skipTest('Pinned WebUI wheel is required for this compatibility test')
        self.assertEqual(distribution.version, '0.11.1')
        source = distribution.locate_file('open_webui/utils/files.py').read_text()
        target = self.root / 'webui/.venv/lib/python3.11/site-packages/open_webui/utils/files.py'
        target.parent.mkdir(parents=True)
        target.write_text(source)
        webui_local_images.harden(self.root)
        first = target.read_text()
        webui_local_images.harden(self.root)
        self.assertEqual(target.read_text(), first)
        self.assertIn(webui_local_images.REPLACEMENT, first)
        namespace = {'Optional': __import__('typing').Optional}
        exec(webui_local_images.REPLACEMENT, namespace)
        self.assertIsNone(asyncio.run(namespace['get_image_base64_from_url']('https://example.org/private.png')))
        target.write_text(source.replace('if url.startswith(\'http\'):', 'if url.startswith(\'https\'):'))
        with self.assertRaises(RuntimeError):
            webui_local_images.harden(self.root)
        loader = distribution.locate_file('open_webui/retrieval/loaders/main.py').read_text()
        loader_target = target.parents[1] / 'retrieval/loaders/main.py'
        loader_target.parent.mkdir(parents=True)
        loader_target.write_text(loader)
        webui_local_images.harden_pdf(self.root)
        import ast
        ast.parse(loader_target.read_text())
        self.assertIn(webui_local_images.PDF_REPLACEMENT, loader_target.read_text())
        webui_local_images.harden_pdf(self.root)


if __name__ == '__main__':
    unittest.main()
