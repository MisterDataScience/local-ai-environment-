"""Fail-closed Captain installation readiness and first-run checks.

The installer runs native generation/worker checks before invoking these checks.
This module does not claim to verify macOS permissions, real peripherals,
network tunnel drops or post-reboot behavior.
"""
import datetime
import json
from pathlib import Path
import subprocess
import time

from common import http
from managed_captain import agent_status, credentials, READY_NAME, ui_status
from text_models import configured_text_models

BASE_CHECKS = ('text', 'image', 'text-after-image', 'video', 'text-after-video')
NATIVE_PENDING = (
    'first_login_after_reboot',
    'sleep_wake_and_process_recovery',
    'microphone_and_macos_permissions',
    'vpn_disconnect_and_dns_leak',
    'captain_access_from_another_tailnet_device',
    'performance_under_target_memory_pressure',
)


class ReadinessError(RuntimeError):
    """Safe, actionable readiness failure suitable for the installer log."""


def acceptance_summary(root, config):
    path = Path(root) / 'acceptance-report.json'
    if not path.is_file():
        raise ReadinessError('Native acceptance report is missing; rerun the Captain installer.')
    report = json.loads(path.read_text())
    rows = report.get('checks')
    if not isinstance(rows, list):
        raise ReadinessError('Native acceptance report has no checks.')
    names = {item.get('name') for item in rows
             if isinstance(item, dict) and item.get('status') == 'passed'}
    required = {"text"} if config.get("install_profile") == "core" else set(BASE_CHECKS)
    required.update('text-' + model for model in configured_text_models(config))
    if config.get('captain', {}).get('enabled'):
        required.update(('native-captain-team', 'native-captain-conversation'))
    missing = sorted(required - names)
    if missing:
        raise ReadinessError('Native acceptance is incomplete (not passed): ' + ', '.join(missing))
    pending = [item.get('name') for item in rows
               if isinstance(item, dict) and item.get('status') == 'not_run']
    return {'passed_checks': sorted(required), 'pending_checks': sorted(set(pending))}


def await_background(root, config, timeout=600, retry_interval=2, *, require_integrations=True):
    """After launchctl bootstrap, ensure UI + gateway + selected Captain are live.

    A listening port alone is not sufficient evidence of a working installation.
    """
    deadline = time.monotonic() + timeout
    last_error = None
    phase = "chat service"
    captain_id = config.get('captain', {}).get('model_id') if config.get('captain', {}).get('enabled') else None
    while time.monotonic() < deadline:
        try:
            phase = 'ordinary chat health (port 8081)'
            web = http('http://127.0.0.1:8081/health', timeout=5)
            if not isinstance(web, dict):
                raise RuntimeError('Chat UI health response is invalid')
            phase = 'gateway model inventory (port 8001)'
            models = http('http://127.0.0.1:8001/v1/models', key=config['api_key'], timeout=5)
            available = {item['id'] for item in models['data']}
            if captain_id and captain_id not in available:
                raise RuntimeError('Captain is not listed by the running gateway')
            if not available:
                raise RuntimeError('Gateway offers no models')
            phase = 'Captain agent API (port 4096)'
            agent = agent_status(root, timeout=5) if captain_id else None
            if captain_id and not (Path(root) / 'control' / READY_NAME).is_file():
                raise RuntimeError('Captain native MCP/tool policy checks have not completed')
            phase = 'Captain chat page and saved sign-in (port 4096)'
            verified = ui_status(root, timeout=5) if captain_id else {}
            phase = 'optional integrations'
            if require_integrations and config.get('web', {}).get('enabled'):
                from web_access import status as web_status
                if web_status(root).get('status') != 'ready':
                    raise RuntimeError('The VPN-only web service is not healthy')
                verified['vpn_web'] = 'passed'
            if require_integrations and config.get('browser', {}).get('enabled'):
                from browser_setup import mcp_probe
                verified['vpn_playwright'] = 'passed' if mcp_probe(timeout=5).get('name') else 'passed'
            if require_integrations and config.get('remote_access', {}).get('enabled'):
                from remote_access import verify_remote_access
                verify_remote_access(root, config['remote_access'])
                verified['private_remote_captain'] = 'passed'
                verified['private_remote_chat_and_media'] = 'passed'
            phase = 'gateway mode'
            status = http('http://127.0.0.1:8001/control/mode', key=config['api_key'], timeout=5)
            if status.get('mode') not in {'normal', 'max'}:
                raise RuntimeError('Captain needs Normal or Max mode. Run AI Modes.command.')
            if status.get('error') or status.get('transitioning'):
                raise RuntimeError('Gateway reports an unavailable or transitioning mode')
            return {'webui_health': 'passed', 'gateway_models': 'passed',
                    'captain_visible': 'passed' if captain_id else 'not_applicable',
                    'captain_native_agents': agent if captain_id else 'not_applicable',
                    'mode': status.get('mode'), **verified}
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            last_error = str(error) if isinstance(error, RuntimeError) else type(error).__name__
            time.sleep(retry_interval)
    raise ReadinessError('Background services did not become ready. Failed check: ' + phase + ': ' + str(last_error)
                       + '. Inspect logs/login-start-error.log and logs/gateway.log')


def write_receipt(root, config, native, background, vault=None, *, require_integrations=False):
    root = Path(root)
    captain = config.get('captain', {})
    if not captain.get('enabled') or captain.get('provider') != 'llama':
        raise RuntimeError('Captain installation selected, but MiniCPM was not configured')
    core = config.get('install_profile') == 'core'
    if not core and config.get('vault', {}).get('enabled') and (
            not isinstance(vault, dict) or vault.get('status') != 'passed'):
        raise RuntimeError('Cryptomator was configured but encrypted workspace tests did not pass')
    if require_integrations:
        for name in ('web', 'browser', 'remote_access'):
            if not config.get(name, {}).get('enabled'):
                raise RuntimeError('Captain installation did not provision mandatory integration: ' + name)
    for category, flag, verification in (
            ('VPN web', 'web', 'vpn_web'),
            ('Playwright browser', 'browser', 'vpn_playwright'),
            ('Tailscale remote Captain', 'remote_access', 'private_remote_captain')):
        if not core and config.get(flag, {}).get('enabled') and background.get(verification) != 'passed':
            raise RuntimeError(category + ' was configured without a passing integration test')
    receipt = {
        'profile': 'core' if core else 'minicpm-captain',
        'status': 'core_ready_with_native_followups',
        'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'native_acceptance': native,
        'background_services': background,
        'encrypted_workspace': vault if vault is not None else {
            'status': 'not_configured', 'reason': 'Vault setup was not included in this installation'},
        'encrypted_workspace_login_unlock': 'owner_must_unlock_cryptomator_after_login',
        'integration_acceptance': {
            'vpn_web': background.get('vpn_web', 'not_configured'),
            'vpn_playwright': background.get('vpn_playwright', 'not_configured'),
            'private_remote_captain': background.get('private_remote_captain', 'not_configured'),
            'private_remote_chat_and_media': background.get('private_remote_chat_and_media', 'not_configured'),
        },
        'pending_physical_acceptance': [name for name in NATIVE_PENDING
            if not core or name in ('first_login_after_reboot', 'sleep_wake_and_process_recovery',
                                   'performance_under_target_memory_pressure')],
        'deferred_permissions_and_accounts': {
            'vpn_browser': 'Configured by Captain installer; requires owner Proton WireGuard key, signed Docker and live VPN tests',
            'remote_captain_ui': 'Configured by Captain installer; off-device Tailnet acceptance pending',
            'desktop_control': 'Separate scoped security mode; cannot be enabled simultaneously with the normal Captain tool profile',
            'external_provider': 'Requires terms-compliant provider permission and per-prompt approval',
            'github_account': 'Requires owner authentication',
        },
        'notice': ('Core Mac acceptance ran; real login/reboot, permissions, peripherals, '
                   'VPN failures and sustained memory pressure remain unverified.'),
    }
    if core:
        from feature_state import snapshot
        receipt['features'] = snapshot(root)
        receipt['notice'] = 'Core text, authenticated UI and real worker dispatch/retirement passed. Optional capabilities have independent readiness receipts.'
        receipt['deferred_permissions_and_accounts']['vpn_browser'] = 'Run Install Encrypted Web Access.command, then Install Browser Automation.command'
        receipt['deferred_permissions_and_accounts']['remote_captain_ui'] = 'Run Install Remote Access.command; off-device acceptance is separate'
    target = root / 'captain-install-readiness.json'
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(target)
    return receipt


def start_login_service(root):
    """Register and start the managed unprivileged LaunchAgent."""
    import login_startup
    login_startup.configure(root, True)
    return login_startup.LABEL


def open_local_ui(root):
    auth = credentials(root)
    print('Captain sign-in username:', auth['username'])
    print('Captain sign-in password:', auth['password'])
    print('These credentials stay on this Mac. The Captain UI is only on loopback.')
    subprocess.run(['/usr/bin/open', '-a', 'Safari', 'http://127.0.0.1:4096'], check=True)


def open_captain(root):
    """Reuse a live supervisor or start an accepted installation."""
    import fcntl
    import os
    from feature_state import effective_config, installation_lock, safe_path
    from login_startup import LABEL

    phase = 'installation files'
    try:
        root = safe_path(Path(root).expanduser()).resolve(strict=True)
        with installation_lock(root, shared=True):
            fd = os.open(safe_path(root / '.captain-open.lock'),
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    print('Captain is already being opened. Check the other Terminal window.')
                    return 0
                config = json.loads((root / 'control/config.json').read_text())
                if not isinstance(config, dict):
                    raise RuntimeError('Saved configuration is invalid. Run Install LOCAL AI Core.command.')
                phase = 'native acceptance'
                acceptance_summary(root, config)
                config = effective_config(root, config)
                if config.get('feature_schema') == 1 and config.get('_feature_status', {}).get('core') != 'ready':
                    raise RuntimeError('Core acceptance is missing, failed or out of date. Run Install LOCAL AI Core.command.')
                if not config.get('captain', {}).get('enabled'):
                    raise RuntimeError('Captain is not enabled. Run Install LOCAL AI Core.command.')
                import resource_modes
                if resource_modes.load(root / 'control') == 'gaming':
                    raise RuntimeError('Gaming mode pauses Captain. Run AI Modes.command and select Normal or Max.')
                phase = 'managed startup'
                runtime_fd = os.open(safe_path(root / '.runtime.lock'),
                                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                with os.fdopen(runtime_fd, 'w') as runtime_lock:
                    try:
                        fcntl.flock(runtime_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        running = True
                    else:
                        running = False
                if not running:
                    print('Starting Captain. Waiting for its services and sign-in checks...')
                    start_login_service(root)
                    result = subprocess.run(['/bin/launchctl', 'kickstart', f'gui/{os.getuid()}/{LABEL}'],
                                            capture_output=True, timeout=30)
                    if result.returncode:
                        raise RuntimeError('Managed startup failed. Check logs/login-start-error.log.')
                phase = 'live services and chat sign-in'
                await_background(root, config, timeout=180, require_integrations=False)
                phase = 'opening Safari'
                open_local_ui(root)
                print('Captain is ready. Type in the chat page opened in Safari on this Mac.')
                return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print('Captain could not open. Failed check: ' + phase + '.')
        if isinstance(error, RuntimeError):
            print(str(error))
        else:
            print('Failure type: ' + type(error).__name__ + '.')
        print('Installation: ' + str(root))
        if phase in {'installation files', 'native acceptance'}:
            print('Run Install LOCAL AI Core.command from the extracted installer to complete or repair setup.')
            print('Details: ' + str(Path(root) / 'acceptance-report.json'))
        else:
            print('Details: ' + str(Path(root) / 'logs/login-start-error.log'))
            print('Captain log: ' + str(Path(root) / 'logs/captain.log'))
            print('Run Check LOCAL AI Setup.command in the installation folder for service status.')
        return 1


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    raise SystemExit(open_captain(parser.parse_args().root))
