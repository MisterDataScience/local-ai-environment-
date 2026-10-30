import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import discord_setup as setup
import discord_runtime as runtime


class DiscordTests(unittest.TestCase):
    def test_installer_can_defer_discord_without_requesting_token_or_voice(self):
        from installer import install_discord_transport
        root = Path('/local-ai')
        with patch.object(setup, 'install') as install, patch.object(setup, 'configure') as configure:
            install_discord_transport(root, None, None, defer_configuration=True)
            install.assert_called_once_with(root, None, None)
            configure.assert_not_called()
            install_discord_transport(root, None, None, defer_configuration=False)
            self.assertEqual(install.call_count, 2)
            configure.assert_called_once_with(root)

    def test_keychain_secret_uses_stdin_not_process_arguments(self):
        token='Secret_token_0123456789'; root=Path('/local-ai')
        with patch.object(setup.subprocess,'run') as run, patch.object(setup,'read_token',return_value=token):
            setup.save_token(root,'123456789012345678',token)
        args,kwargs=run.call_args
        self.assertNotIn(token,str(args)); self.assertIn(token,kwargs['input'])
        self.assertEqual(args[0],['/usr/bin/security','-i'])

    def test_invalid_credential_cannot_inject_keychain_commands(self):
        with patch.object(setup.subprocess,'run') as run:
            with self.assertRaises(ValueError):setup.save_token(Path('/ai'),'123456789012345678','bad\ncommand')
            run.assert_not_called()

    def test_owner_and_private_bot_required_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'control').mkdir();(root/'control/config.json').write_text('{}')
            with patch.object(setup.getpass,'getpass',return_value='safe_token_0123456789'), patch.object(setup,'discord',side_effect=[{'bot':True},{'owner':{'id':'123456789012345678'},'bot_public':True}]), patch.object(setup,'save_token') as save:
                with self.assertRaises(ValueError):setup.configure(root)
                save.assert_not_called()

    def test_supervisor_releases_voice_on_gaming_and_restarts_on_ready(self):
        s=runtime.DiscordSupervisor(Path('/ai'),{'discord':{'enabled':True}})
        ready={'mode':'normal','instance_id':'one','epoch':1}
        process=Mock();process.poll.return_value=None
        with patch.object(runtime,'port_open',return_value=False),patch.object(runtime,'launch',return_value=process) as launch,patch.object(runtime,'stop_process') as stop:
            s.tick(ready);s.tick(ready);self.assertEqual(launch.call_count,1)
            s.tick({**ready,'mode':'gaming'});stop.assert_called_once();self.assertIsNone(s.process)
            s.tick({**ready,'epoch':2});self.assertEqual(launch.call_count,2)

    def test_supervisor_does_not_take_over_manual_agent(self):
        s=runtime.DiscordSupervisor(Path('/ai'),{'discord':{'enabled':True}})
        with patch.object(runtime,'port_open',return_value=True),patch.object(runtime,'launch') as launch:
            s.tick({'mode':'normal'});launch.assert_not_called()

    def test_crashed_adapter_has_retry_backoff(self):
        s=runtime.DiscordSupervisor(Path('/ai'),{'discord':{'enabled':True}})
        s.epoch=('one',1,'normal');s.process=Mock();s.process.poll.return_value=1
        with patch.object(runtime.time,'monotonic',return_value=100),patch.object(runtime,'launch') as launch:
            s.tick({'mode':'normal','instance_id':'one','epoch':1});launch.assert_not_called();self.assertEqual(s.retry_at,130)
