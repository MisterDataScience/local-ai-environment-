"""Independent, resumable feature installers over the existing pinned modules.

Run only this feature's dependencies and acceptance. Never reset owner settings,
reinstall core, replace credentials, or treat a load check as a live call.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

from feature_state import (FEATURES, atomic_json, effective_config, hashes,
                           installation_lock, migrate, read, safe_path, snapshot, write)


class AwaitingUser(RuntimeError):
    pass


def configuration(root):
    return json.loads(safe_path(root / 'control/config.json').read_text())


def save_section(root, key, settings):
    config = configuration(root)
    config[key] = {**config.get(key, {}), **settings}
    atomic_json(root / 'control/config.json', config)


def prompt(text):
    if not sys.stdin.isatty():
        raise AwaitingUser('Run this installer in Terminal when its inputs are ready.')
    try:
        return input(text).strip()
    except EOFError:
        raise AwaitingUser('Input was deferred. Rerun this installer in Terminal.') from None


def require_input(text, action):
    value = prompt(text)
    if not value:
        raise AwaitingUser(action)
    return value


def mark_installed(root, feature, version, files):
    write(root, feature, 'installed', installed_version=version,
          validated_hashes=hashes(files), last_failure=None)


def install_speech(root, uv):
    from installer import run
    from voice_setup import install, register
    settings = install(root, uv, run)
    save_section(root, 'speech', settings)
    mark_installed(root, 'speech', settings['model_revision'], {
        'artifacts': root / 'voice-engine/artifacts.json',
        'dependencies': root / 'voice-engine/installed.json'})
    if not (root / 'voice-engine/voices/default.json').is_file():
        source = require_input('Reference WAV path (blank to finish later): ',
            'Prepare a 3 to 30 second 16-bit PCM WAV and its exact transcript, then rerun Install Local Speech.command.')
        transcript = require_input('Exact words spoken in the WAV (blank to finish later): ',
            'Prepare the reference transcript, then rerun Install Local Speech.command.')
        # No replacement of an existing voice, including a half-registered one.
        register(root, 'default', source, transcript)
    import feature_checks
    return lambda: feature_checks.speech(root, configuration(root))


def install_workspace(root, uv):
    from installer import download, run
    from workspace_setup import install_cryptomator
    from workspace_install import configure_during_install
    app = install_cryptomator(root, download, run)
    config = configuration(root)
    if 'cryptomator_app' not in config:
        config['cryptomator_app'] = str(app)
        atomic_json(root / 'control/config.json', config)
    mark_installed(root, 'workspace', 'signed-Cryptomator', {})
    if not config.get('vault', {}).get('enabled'):
        if prompt('Ready to create/unlock a Cryptomator vault now? Type YES, or Enter to finish later: ') != 'YES':
            raise AwaitingUser('Unlock your Cryptomator vault, then rerun Install Encrypted Workspace.command.')
    def check():
        _, report = configure_during_install(root, app, prompt=lambda text: prompt(text))
        return report
    return check


def install_conversation(root, uv):
    from installer import run
    from conversation_setup import install
    settings = install(root, uv, run)
    save_section(root, 'conversation', settings)
    mark_installed(root, 'conversation', settings['stt_revision'], {
        'artifacts': root / 'voice-engine/conversation-artifacts.json',
        'dependencies': root / 'voice-engine/conversation-installed.json'})
    from feature_checks import conversation
    return lambda: conversation(root)


def install_discord(root, uv):
    from installer import download, run
    from discord_setup import install, configure, read_token
    install(root, download, run)
    mark_installed(root, 'discord', 'node-24.21.0', {'dependencies': root / 'discord-engine/installed.json'})
    existing = configuration(root).get('discord', {})
    if not existing.get('application_id'):
        if prompt('Ready to register your private Discord bot now? Type YES, or Enter to finish later: ') != 'YES':
            raise AwaitingUser('Prepare a private Discord bot token, then rerun Install Discord Voice.command.')
    # Existing credentials are read from Keychain, never replaced on rerun.
    if existing.get('application_id'):
        read_token(root, existing['application_id'])
    else:
        configure(root)
    def check():
        from discord_setup import discord
        config = configuration(root)['discord']
        token = read_token(root, config['application_id'])
        me = discord(token, '/users/@me')
        application = discord(token, '/oauth2/applications/@me')
        guild = discord(token, '/guilds/' + config['guild_id'])
        if application.get('bot_public', True) or guild.get('owner_id') != config['owner_id']:
            raise RuntimeError('Discord bot or server is no longer private and owner controlled')
        channel = discord(token, '/channels/' + config['channel_id'])
        if me.get('id') != config['bot_id'] or channel.get('guild_id') != config['guild_id'] or channel.get('type') != 2:
            raise RuntimeError('Saved Discord bot/channel identity did not match')
        overwrites = {item['id']: item for item in channel.get('permission_overwrites', [])}
        if not (int(overwrites.get(config['guild_id'], {}).get('deny', 0)) & 1024):
            raise RuntimeError('Discord channel is not private')
        for identifier, entry in overwrites.items():
            if identifier not in {config['owner_id'], config['bot_id']} and int(entry.get('allow', 0)) & 1024:
                raise RuntimeError('Discord channel permits an additional viewer')
        save_section(root, 'discord', {'enabled': True})
        # Authentication + codec do not establish an end-to-end private call.
        return {'bot_and_private_channel': 'passed', 'live_call': 'not_run'}
    return check


def install_media(root, uv):
    from installer import MODELS, SOURCE, download, install_comfy
    install_comfy(root, uv, root / 'install-state.json')
    for relative, url, checksum in MODELS:
        download(url, root / 'ComfyUI/models' / relative, checksum)
    shutil.copytree(SOURCE / 'comfy_vault', root / 'ComfyUI/custom_nodes/local_ai_vault', dirs_exist_ok=True)
    save_section(root, 'media_generation', {'enabled': True})
    mark_installed(root, 'media', 'ComfyUI-v0.38.0', {
        relative: root / 'ComfyUI/models' / relative for relative, _, _ in MODELS})
    from feature_checks import media
    return lambda: media(root)


def install_office(root, uv):
    from installer import download, run
    from office_setup import install, binary_path
    settings = install(root, download, run)
    save_section(root, 'office', settings)
    mark_installed(root, 'office', settings['version'], {'binary': binary_path(root)})
    # install() already executed the real sandbox/MCP document acceptance.
    return lambda: {'sandbox_and_office_mcp': 'passed'}


def install_web(root, uv):
    from installer import download
    from docker_setup import install, SHA256
    try:
        install(root, download)
    except RuntimeError as error:
        if 'licence/permissions' in str(error):
            raise AwaitingUser('Complete Docker licence and permissions in its app, then rerun Install Encrypted Web Access.command.') from None
        raise
    mark_installed(root, 'web', 'pinned-Docker-and-Gluetun', {'docker_archive': root / 'cache/docker-desktop-4.91.0-arm64.dmg'})
    config = configuration(root)
    if not (root / 'web/vpn.env').is_file():
        if prompt('Ready to supply your Proton WireGuard private key? Type YES, or Enter to finish later: ') != 'YES':
            raise AwaitingUser('Prepare your Proton WireGuard configuration, then rerun Install Encrypted Web Access.command.')
    from web_access import configure, start
    from feature_checks import recover_web_acceptance
    recover_web_acceptance(root)
    if config.get('web', {}).get('enabled') and (root / 'web/compose.json').is_file():
        start(root)
    else:
        configure(root)
    from feature_checks import web
    return lambda: web(root, configuration(root))


def install_browser(root, uv):
    from browser_setup import configure
    configure(root)
    mark_installed(root, 'browser', 'pinned-Playwright-MCP', {'images': root / 'web/images.json'})
    from feature_checks import browser
    return lambda: browser(root)


def install_remote(root, uv):
    from remote_access import install_client, configure, TAILSCALE_VERSION
    install_client(root)
    mark_installed(root, 'remote', TAILSCALE_VERSION, {})
    if not configuration(root).get('remote_access', {}).get('enabled'):
        if prompt('Ready to authorise your personal Tailscale account? Type YES, or Enter to finish later: ') != 'YES':
            raise AwaitingUser('Authorise Tailscale on this Mac, then rerun Install Remote Access.command.')
        configure(root)
    from feature_checks import remote
    return lambda: remote(root)


def install_github(root, uv):
    from account_tools import configure, connection
    if not configuration(root).get('account_tools', {}).get('github'):
        if not sys.stdin.isatty() or not configure(root):
            raise AwaitingUser('Prepare a scoped GitHub token, then rerun Connect GitHub.command.')
    connection(root)  # Private-file permission check, never log its result.
    mark_installed(root, 'github', 'official-MCP', {})
    from feature_checks import github
    return lambda: github(root)


INSTALLERS = {name: globals()['install_' + name] for name in FEATURES if name != 'core'}


def ensure_stopped(root):
    import fcntl
    from common import PORTS, port_open
    with safe_path(root / '.runtime.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Run Stop Local AI.command before installing a feature.') from None
    if any(port_open(port) for port in (*PORTS.values(), 4096, 8003)):
        raise RuntimeError('Close Local AI and Work Agent before installing. No existing process was stopped.')


def run_feature(root, feature, uv, *, prepare_only=False):
    launcher = FEATURES[feature][0]
    config = configuration(root)
    try:
        previous = read(root, feature)
    except (OSError, ValueError, RuntimeError):
        print(feature + ': failed. Its invalid receipt is preserved. Repair state/features/' + feature + '.json, then rerun ' + launcher)
        return False
    view = effective_config(root, config)
    missing = [dep for dep in FEATURES[feature][2]
               if view.get('_feature_status', {}).get(dep, 'not_installed') != 'ready']
    if missing:
        action = 'Run ' + ', then '.join(FEATURES[dep][0] for dep in missing) + ', then ' + launcher
        write(root, feature, 'awaiting_user', next_action=action, last_failure=None)
        print(feature + ': awaiting_user. ' + action)
        return False
    print('Installing ' + feature + '. Only this feature will be configured and checked.')
    # Mark a previously ready receipt unavailable BEFORE changing any artifacts.
    # An interrupted run remains installed/configured/testing, never falsely ready.
    write(root, feature, 'installed' if previous.get('installed_version') else 'not_installed',
          acceptance={}, current_stage='installing', next_action='Rerun ' + launcher)
    try:
        if prepare_only:
            raise AwaitingUser('Run ' + launcher + ' in Terminal to install and configure this feature.')
        check = INSTALLERS[feature](root, uv)
        write(root, feature, 'configured', next_action='Native acceptance is required.')
        write(root, feature, 'testing')
        report = check()
        if not isinstance(report, dict) or not any(value == 'passed' for value in report.values()):
            raise RuntimeError('Feature acceptance did not record a passing native check')
        if feature == 'discord':
            write(root, feature, 'configured', acceptance=report, last_failure=None,
                  next_action='Run Test Discord Voice.command for a supervised private call acceptance.')
            print('discord: configured. A real private call has not passed. Run Test Discord Voice.command.')
            return False
        write(root, feature, 'ready', acceptance=report, last_failure=None, next_action='',
              pending_checks=[key for key, value in report.items() if value == 'not_run'])
        print(feature + ': ready. Native checks passed; physical follow-ups are listed by Check LOCAL AI Setup.command.')
        return True
    except (AwaitingUser, EOFError, KeyboardInterrupt) as error:
        action = str(error) if isinstance(error, AwaitingUser) else ("Input was deferred. Rerun " + launcher + ".")
        write(root, feature, 'awaiting_user', next_action=action, last_failure=None)
        print(feature + ': awaiting_user. ' + action)
        return False
    except Exception as error:
        # Third-party exceptions may contain requests or secret environment data.
        # Never copy their text/traceback into logs, receipts or the console.
        action = 'Check this feature\'s prerequisites, then rerun ' + launcher
        code = type(error).__name__
        if feature == 'discord' and 'HTTP 401' in str(error):
            action = 'Discord rejected the bot token (HTTP 401). Run Connect Discord.command to replace it explicitly, then rerun ' + launcher
        elif feature == 'speech':
            action = 'Check the local model, WAV format, transcript and vault unlock if configured, then rerun ' + launcher
        write(root, feature, 'failed', last_failure=code, next_action=action)
        print(feature + ': failed (' + code + '). ' + action)
        return False


def status(root):
    config = effective_config(root, configuration(root))
    for feature, row in snapshot(root).items():
        effective = config.get('_feature_status', {}).get(feature, row['status'])
        print(('Core' if feature == 'core' else feature) + ': ' + effective)
        if row.get('next_action'):
            print('  ' + row['next_action'])
        if effective != 'ready':
            print('  ' + FEATURES[feature][0])
        for check in row.get('pending_checks', []):
            print('  Not run: ' + check)
    from common import http
    try:
        http('http://127.0.0.1:8001/health', timeout=3)
        print('Gateway: responding on loopback')
    except (OSError, ValueError):
        print('Gateway: stopped or unavailable. Run Start Local AI.command.')
    print('Readiness records native acceptance at the last check. It is not a live guarantee.')


def make_launchers(root):
    for feature, (label, _, _) in FEATURES.items():
        if feature == 'core':
            continue
        path = root / label
        path.write_text('#!/bin/bash\nset -euo pipefail\ncd ' + shlex.quote(str(root / 'control')) +
            '\nexec .venv/bin/python feature_install.py --root ' + shlex.quote(str(root)) +
            ' --feature ' + feature + ' "$@"\n')
        path.chmod(0o755)
    for label, feature in (('Enable Web Access', 'web'), ('Enable Browser', 'browser'),
                           ('Enable Remote Access', 'remote'), ('Configure AI Workspace', 'workspace'),
                           ('Configure Voice', 'speech'), ('Connect Discord', 'discord')):
        path = root / (label + '.command')
        repair = ' --replace-discord-token' if feature == 'discord' else ''
        path.write_text('#!/bin/bash\nset -euo pipefail\ncd ' + shlex.quote(str(root / 'control')) +
            '\nexec .venv/bin/python feature_install.py --root ' + shlex.quote(str(root)) +
            ' --feature ' + feature + repair + ' \"$@\"\n')
        path.chmod(0o755)
    path = root / 'Install Everything.command'
    path.write_text('#!/bin/bash\nset -euo pipefail\ncd ' + shlex.quote(str(root / 'control')) +
        '\nexec .venv/bin/python feature_install.py --root ' + shlex.quote(str(root)) + ' --everything\n')
    path.chmod(0o755)
    path = root / 'Test Discord Voice.command'
    path.write_text('#!/bin/bash\nset -euo pipefail\ncd ' + shlex.quote(str(root / 'control')) +
        '\nexec .venv/bin/python feature_install.py --root ' + shlex.quote(str(root)) + ' --test-discord\n')
    path.chmod(0o755)
    path = root / 'Check LOCAL AI Setup.command'
    path.write_text('#!/bin/bash\nset -euo pipefail\ncd ' + shlex.quote(str(root / 'control')) +
        '\nexec .venv/bin/python feature_install.py --root ' + shlex.quote(str(root)) + ' --status\n')
    path.chmod(0o755)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.home() / 'LocalAI-Automated')
    parser.add_argument('--feature', choices=list(INSTALLERS))
    parser.add_argument('--everything', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--test-discord', action='store_true')
    parser.add_argument('--replace-discord-token', action='store_true', help='Explicit replacement through the credential repair launcher.')
    args = parser.parse_args()
    root = safe_path(args.root.expanduser()).resolve()
    if not (root / 'control/config.json').is_file():
        raise SystemExit('Core installation missing. Run Install LOCAL AI Core.command first.')
    if args.status:
        status(root)
        return 0
    if not args.feature and not args.everything and not args.test_discord:
        parser.error('Choose --feature, --everything or --status')
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('Feature installers require native Apple Silicon macOS.')
    uv = root / 'tools/uv/uv'
    if not uv.is_file():
        raise SystemExit('Verified uv is missing. Rerun Install LOCAL AI Core.command.')
    if args.replace_discord_token and args.feature != 'discord':
        parser.error('--replace-discord-token requires --feature discord')
    with installation_lock(root):
        ensure_stopped(root)
        if configuration(root).get('feature_schema') != 1:
            raise RuntimeError('Rerun Install LOCAL AI Core.command once to migrate this installation safely.')
        if args.replace_discord_token:
            from discord_setup import configure
            if read(root, 'conversation')['status'] != 'ready':
                raise RuntimeError('Run Install Live Conversation.command before replacing Discord credentials.')
            configure(root, force=True)
        if args.test_discord:
            dependencies = FEATURES['discord'][2]
            if any(read(root, name)['status'] != 'ready' for name in dependencies):
                raise RuntimeError('Run Install Live Conversation.command before testing Discord.')
            if not configuration(root).get('discord', {}).get('enabled'):
                raise RuntimeError('Run Install Discord Voice.command before its live acceptance.')
            write(root, 'discord', 'testing')
            try:
                from feature_checks import discord_live
                report = discord_live(root)
                write(root, 'discord', 'ready', acceptance=report, pending_checks=[], last_failure=None, next_action='')
                print('discord: ready. Real private call, speech, playback and interruption observed.')
                return 0
            except (Exception, KeyboardInterrupt):
                write(root, 'discord', 'configured', next_action='Run Test Discord Voice.command to complete a private call acceptance.')
                print('discord: configured. Live call acceptance did not finish; core chat is preserved.')
                return 2
        features = list(INSTALLERS) if args.everything else [args.feature]
        results = [run_feature(root, feature, uv) for feature in features]
    print('Completed files and owner settings are preserved. Run Start Local AI.command to resume chat.')
    return 0 if all(results) else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        raise SystemExit(str(error))
    except (OSError, ValueError):
        raise SystemExit('Feature setup stopped: configuration or receipt is invalid. Preserve the files and run Check LOCAL AI Setup.command.')
