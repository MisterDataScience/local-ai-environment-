"""Unattended Captain Docker bootstrap — authorisation and fail-closed regressions."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import docker_setup


class DockerSetupTests(unittest.TestCase):
    def test_vendor_signature_and_gatekeeper_both_required(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / 'Docker.app'
            app.mkdir()
            with patch.object(docker_setup, 'run', side_effect=subprocess.CalledProcessError(1, ['codesign'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    docker_setup.verify(app)

    def test_symlink_app_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / 'Docker.app'
            app.symlink_to(Path(directory) / 'unexpected')
            with patch.object(docker_setup, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'regular Docker'):
                    docker_setup.verify(app)
            run.assert_not_called()

    def test_local_docker_context_and_compose_required(self):
        endpoint = {'Endpoints': {'docker': {'Host': 'tcp://remote:2375'}}}
        with patch.object(docker_setup, 'run', return_value=Mock(stdout=json.dumps([endpoint]))) as run:
            with self.assertRaisesRegex(RuntimeError, 'local Unix'):
                docker_setup.ready('docker')
            self.assertEqual(run.call_count, 1)
        endpoint['Endpoints']['docker']['Host'] = 'unix:///Users/test/.docker/run/docker.sock'
        with patch.object(docker_setup, 'run', side_effect=[
                Mock(stdout=json.dumps([endpoint])), Mock(stdout=''), Mock(stdout='')]) as run:
            docker_setup.ready('docker')
            self.assertEqual(run.call_count, 3)
            self.assertEqual(run.call_args.args[0][-2:], ['compose', 'version'])

    def test_existing_signed_app_kept_and_no_automatic_licence_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / 'Docker.app'
            app.mkdir()
            with patch.object(docker_setup, 'APP', app), \
                 patch.object(docker_setup, 'verify') as verify, \
                 patch.object(docker_setup, 'run') as run, \
                 patch.object(docker_setup, 'docker_binary', return_value='docker'), \
                 patch.object(docker_setup, 'ready'):
                result = docker_setup.install(Path(directory), Mock())
            self.assertEqual(result, 'docker')
            verify.assert_called_once_with(app)
            self.assertEqual(run.call_args.args[0][:3], ['/usr/bin/open', '-a', str(app)])
            self.assertNotIn('accept-license', str(run.call_args_list))

    def test_install_confirmation_is_left_to_docker_gui(self):
        source = Path(__file__).resolve().parents[1].joinpath('docker_setup.py').read_text()
        self.assertNotIn("'--accept-license'", source)
        self.assertNotIn('shell=True', source)
        self.assertIn('administrator privileges', source)


if __name__ == '__main__':
    unittest.main()
