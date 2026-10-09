import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_setup as office
from office_mcp import compact_schema, compact_response


class OfficeTests(unittest.TestCase):
    def test_download_mismatch_never_executes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            def download(url, path, checksum):
                path.parent.mkdir(parents=True)
                path.write_bytes(b'untrusted')
            runner = Mock()
            with self.assertRaises(RuntimeError): office.install(root, download, runner)
            runner.assert_not_called()
            self.assertFalse(office.binary_path(root).exists())

    def test_existing_binary_is_verified_again(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            binary = office.binary_path(root)
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'changed')
            runner = Mock()
            with self.assertRaises(RuntimeError): office.install(root, Mock(), runner)
            runner.assert_not_called()

    def test_configuration_project_scope_and_agent_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            project = root / 'work-agent/projects/123'
            project.mkdir(parents=True)
            settings = {'permission': {}, 'agent': {role: {'permission': {'*': 'deny'}}
                        for role in ('plan','build','coder','analyst','document')}}
            with patch.object(office, 'verify_binary'):
                office.configure(root, project, settings, {'office': {'enabled': True}})
                with self.assertRaises(ValueError):
                    office.configure(root, root, copy.deepcopy(settings), {'office': {'enabled': True}})
            self.assertEqual(settings['mcp']['aioffice']['type'], 'local')
            self.assertIn(str(project), settings['mcp']['aioffice']['command'])
            self.assertEqual(settings['agent']['plan']['permission']['aioffice_*'], 'deny')
            self.assertNotIn('aioffice_office_edit', settings['agent']['plan']['permission'])
            self.assertEqual(settings['agent']['build']['permission']['aioffice_office_edit'], 'ask')
            for role in ('coder','analyst','document'):
                self.assertEqual(settings['agent'][role]['permission'], {'*': 'deny'})
            self.assertEqual(settings['agent']['build']['permission']['aioffice_office_read'], 'allow')

    def test_environment_drops_account_keys_and_user_engine_overrides(self):
        with patch.dict(os.environ, {'LOCAL_AI_GATEWAY_KEY':'secret','OPENAI_API_KEY':'secret',
                         'AIOFFICE_MAX_FILE_MB':'99999','AIOFFICE_WORKSPACE':'/','DOTNET_STARTUP_HOOKS':'evil'}):
            env = office.engine_environment()
        for name in ('LOCAL_AI_GATEWAY_KEY','OPENAI_API_KEY','AIOFFICE_WORKSPACE','DOTNET_STARTUP_HOOKS'):
            self.assertNotIn(name, env)
        self.assertEqual(env['AIOFFICE_MAX_FILE_MB'], '50')
        self.assertEqual(env['DOTNET_GCHeapHardLimit'], '0x20000000')

    def test_compact_schema_preserves_property_names_and_validation(self):
        schema = {'type':'object','description':'long','properties':{
            'title':{'type':'string','description':'long'}, 'description':{'type':'string'},
            'ops':{'type':'array','minItems':1,'items':{'type':'object','properties':{
                'props':{'type':'object','additionalProperties':{'type':'string'}}}}}},
            'required':['title'], 'additionalProperties':False}
        slim = compact_schema(schema)
        self.assertIn('title', slim['properties'])
        self.assertIn('description', slim['properties'])
        self.assertEqual(slim['required'], schema['required'])
        self.assertEqual(slim['properties']['ops']['items']['properties']['props']['additionalProperties'], {'type':'string'})
        self.assertNotIn('description', slim)
        result = json.loads(compact_response(json.dumps({'id':1,'result':{'tools':[
            {'name':'office_create','inputSchema':schema}, {'name':'preview_open','inputSchema':{}}]}})))
        self.assertEqual([t['name'] for t in result['result']['tools']], ['office_create'])
        error = {'jsonrpc':'2.0','id':2,'error':{'code':-1,'message':'test'}}
        self.assertEqual(json.loads(compact_response(json.dumps(error))), error)

    def test_network_sandbox_is_required(self):
        with patch.object(office.sys, 'platform', 'linux'):
            with self.assertRaises(RuntimeError): office.engine_command(Path('/binary'), Path('/workspace'))
        with patch.object(office.sys, 'platform', 'darwin'), patch.object(Path, 'is_file', return_value=True):
            cmd = office.engine_command(Path('/binary'), Path('/workspace'))
        self.assertEqual(cmd[:3], ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)'])
        self.assertEqual(cmd[-3:], ['mcp','--workspace','/workspace'])

    def test_runtime_native_mcp_failure_is_not_silent(self):
        env={'OPENCODE_CONFIG_CONTENT':json.dumps({'mcp':{'aioffice':{}}}), 'OPENCODE_SERVER_PASSWORD':'local'}
        response=Mock()
        response.read.return_value=b'{"aioffice":{"status":"failed","error":"missing"}}'
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        process=Mock(); process.poll.return_value=None
        with patch.object(office, 'urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'failed to connect'): office.verify_connection(process,env)


if __name__ == '__main__': unittest.main()
