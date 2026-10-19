"""One supervised background process for private Tailscale recovery."""
import argparse
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from common import launch, stop_process
from remote_access import PublicFunnelError

FUNNEL_EXIT = 78


def recover_remote(remote):
    """Reopen the signed-in app before checking/repairing only owned routes."""
    from remote_access import APP, cli_json, reconcile_private_routes
    try:
        running = cli_json('status', '--json').get('BackendState') == 'Running'
    except (OSError, ValueError, subprocess.SubprocessError):
        running = False
    if not running and APP.is_dir() and not APP.is_symlink():
        subprocess.run(['/usr/bin/open', '-a', str(APP)], check=True, timeout=20)
    return reconcile_private_routes(remote)


class RemoteRecovery:
    """Nonblocking polling; no overlapping attempts or detached shutdown work."""
    def __init__(self, root, remote, interval=120):
        self.root = Path(root)
        self.remote = dict(remote)
        self.interval = interval
        self.process = None
        self.next_attempt = 0
        self.verify_next = True
        self.closed = False

    def tick(self, now=None):
        if self.closed or not self.remote.get('enabled'):
            return
        now = time.monotonic() if now is None else now
        if self.process is not None:
            result = self.process.poll()
            if result is None:
                return
            self.process = None
            self.next_attempt = now + self.interval
            self.verify_next = result != 0
            if result == FUNNEL_EXIT:
                raise PublicFunnelError('Public Tailscale Funnel detected; stopping private services')
            if result:
                logging.warning('Tailscale recovery is waiting; see logs/remote-recovery.log.')
            else:
                logging.info('Private Tailscale recovery/check completed.')
        if now < self.next_attempt:
            return
        command = [self.root / 'control/.venv/bin/python',
                   self.root / 'control/remote_recovery.py', '--root', self.root,
                   '--hostname', self.remote['hostname'], '--supervisor-pid', str(os.getpid())]
        if self.verify_next:
            command.append('--verify')
        environment = {key: value for key, value in os.environ.items() if key in {
            'HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'USER', 'SSL_CERT_FILE', 'SSL_CERT_DIR'}}
        try:
            self.process = launch(command, self.root / 'control',
                                  self.root / 'logs/remote-recovery.log', environment)
        except OSError:
            self.next_attempt = now + self.interval
            logging.warning('Tailscale recovery worker could not start; retrying later.')

    def close(self, timeout=10):
        self.closed = True
        if self.process is not None:
            # A bounded grace allows reconciliation's rollback/finally cleanup.
            # Escalation also kills inherited CLI children in the private group.
            stop_process(self.process, timeout=timeout)
            self.process = None


def notify_funnel(supervisor_pid):
    # The direct parent relation authorizes this signal and prevents PID reuse
    # from targeting an unrelated process after the supervisor has died.
    if os.getppid() == supervisor_pid:
        try:
            os.kill(supervisor_pid, signal.SIGUSR1)
        except OSError:
            pass  # The distinct exit code also reaches the next parent tick.


def monitor_parent(supervisor_pid, done):
    while not done.wait(1):
        if os.getppid() != supervisor_pid:
            # The worker is launched as its own process-group leader. Cancel
            # the worker and any running CLI if its supervisor was killed.
            os.killpg(os.getpid(), signal.SIGTERM)
            return


def run(root, expected_hostname, verify=False):
    config = json.loads((root / 'control/config.json').read_text())
    remote = config.get('remote_access', {})
    if not remote.get('enabled') or remote.get('hostname') != expected_hostname:
        raise RuntimeError('Remote settings changed; restart Local AI before repairing routes')
    repaired = recover_remote(remote)
    if repaired or verify:
        from remote_access import verify_remote_access
        verify_remote_access(root, remote)
    return repaired


def failed_report(root):
    from remote_access import atomic_json
    try:
        atomic_json(root / 'remote-acceptance-report.json', {
            'status': 'failed', 'checked_at': time.time(),
            'error': 'Private recovery/check failed; inspect logs/remote-recovery.log',
            'other_device_browser_test': 'pending'})
    except OSError:
        logging.warning('Remote failure report could not be written.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--supervisor-pid', type=int, required=True)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if os.getpgrp() != os.getpid() or os.getppid() != args.supervisor_pid:
        return 1
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    done = threading.Event()
    monitor = threading.Thread(target=monitor_parent, args=(args.supervisor_pid, done), daemon=True)
    monitor.start()
    try:
        repaired = run(args.root, args.hostname, args.verify)
        logging.info('Private Tailscale check finished; repaired %s routes.', len(repaired))
        return 0
    except PublicFunnelError:
        notify_funnel(args.supervisor_pid)
        failed_report(args.root)
        logging.error('Public Funnel detected on a managed port; supervisor shutdown requested.')
        return FUNNEL_EXIT
    except KeyboardInterrupt:
        return 130
    except Exception:
        failed_report(args.root)
        # No response bodies, credentials or untrusted CLI output in the log.
        logging.warning('Private Tailscale recovery/check failed; local service monitoring continues.')
        return 1
    finally:
        done.set()
        monitor.join(timeout=2)


if __name__ == '__main__':
    raise SystemExit(main())
