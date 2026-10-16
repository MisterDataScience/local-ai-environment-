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
from managed_captain import agent_status, credentials, READY_NAME
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


def acceptance_summary(root, config):
    path = Path(root) / 'acceptance-report.json'
    if not path.is_file():
        raise RuntimeError('Native acceptance report is missing; rerun the Captain installer.')
    report = json.loads(path.read_text())
    rows = report.get('checks')
    if not isinstance(rows, list):
        raise RuntimeError('Native acceptance report has no checks.')
    names = {item.get('name') for item in rows
             if isinstance(item, dict) and item.get('status') == 'passed'}
    required = set(BASE_CHECKS)
    required.update('text-' + model for model in configured_text_models(config))
    if config.get('captain', {}).get('enabled'):
        required.add('native-captain-team')
    missing = sorted(required - names)
    if missing:
        raise RuntimeError('Native acceptance is incomplete (not passed): ' + ', '.join(missing))
    pending = [item.get('name') for item in rows
               if isinstance(item, dict) and item.get('status') == 'not_run']
    return {'passed_checks': sorted(required), 'pending_checks': sorted(set(pending))}


def await_background(root, config, timeout=600, retry_interval=2):
    """After launchctl bootstrap, ensure UI + gateway + selected Captain are live.

    A listening port alone is not sufficient evidence of a working installation.
    """
    deadline = time.monotonic() + timeout
    last_error = None
    captain_id = config.get('captain', {}).get('model_id') if config.get('captain', {}).get('enabled') else None
    while time.monotonic() < deadline:
        try:
            web = http('http://127.0.0.1:8081/health', timeout=5)
            if not isinstance(web, dict):
                raise RuntimeError('Chat UI health response is invalid')
            models = http('http://127.0.0.1:8001/v1/models', key=config['api_key'], timeout=5)
            available = {item['id'] for item in models['data']}
            if captain_id and captain_id not in available:
                raise RuntimeError('Captain is not listed by the running gateway')
            if not available:
                raise RuntimeError('Gateway offers no models')
            agent = agent_status(root, timeout=5) if captain_id else None
            if captain_id and not (Path(root) / 'control' / READY_NAME).is_file():
                raise RuntimeError('Captain native MCP/tool policy checks have not completed')
            verified = {}
            if config.get('web', {}).get('enabled'):
                from web_access import status as web_status
                if web_status(root).get('status') != 'ready':
                    raise RuntimeError('The VPN-only web service is not healthy')
                verified['vpn_web'] = 'passed'
            if config.get('browser', {}).get('enabled'):
                from browser_setup import mcp_probe
                verified['vpn_playwright'] = 'passed' if mcp_probe(timeout=5).get('name') else 'passed'
            if config.get('remote_access', {}).get('enabled'):
                from remote_access import verify_remote_access
                verify_remote_access(root, config['remote_access'])
                verified['private_remote_captain'] = 'passed'
                verified['private_remote_chat_and_media'] = 'passed'
            status = http('http://127.0.0.1:8001/control/mode', key=config['api_key'], timeout=5)
            if status.get('error') or status.get('transitioning'):
                raise RuntimeError('Gateway reports an unavailable or transitioning mode')
            return {'webui_health': 'passed', 'gateway_models': 'passed',
                    'captain_visible': 'passed' if captain_id else 'not_applicable',
                    'captain_native_agents': agent if captain_id else 'not_applicable',
                    'mode': status.get('mode'), **verified}
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            last_error = error
            time.sleep(retry_interval)
    raise RuntimeError('Background services did not become ready: ' + str(last_error)
                       + '. Inspect logs/login-start-error.log and logs/gateway.log')


def write_receipt(root, config, native, background, vault=None):
    root = Path(root)
    captain = config.get('captain', {})
    if not captain.get('enabled') or captain.get('provider') != 'llama':
        raise RuntimeError('Captain installation selected, but MiniCPM was not configured')
    if config.get('vault', {}).get('enabled') and (
            not isinstance(vault, dict) or vault.get('status') != 'passed'):
        raise RuntimeError('Cryptomator was configured but encrypted workspace tests did not pass')
    for category, flag, verification in (
            ('VPN web', 'web', 'vpn_web'),
            ('Playwright browser', 'browser', 'vpn_playwright'),
            ('Tailscale remote Captain', 'remote_access', 'private_remote_captain')):
        if config.get(flag, {}).get('enabled') and background.get(verification) != 'passed':
            raise RuntimeError(category + ' was configured without a passing integration test')
    receipt = {
        'profile': 'minicpm-captain',
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
        'pending_physical_acceptance': list(NATIVE_PENDING),
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
