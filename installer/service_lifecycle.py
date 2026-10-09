"""Recover only recorded, still-identical Local AI child process groups."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
from scheduled_tasks import atomic_json


def fingerprint(pid):
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
                            capture_output=True, text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else ''


def record(root, processes):
    owned = []
    for name, process in processes:
        identity = fingerprint(process.pid)
        if identity and str(root) in identity and os.getpgid(process.pid) == process.pid:
            owned.append({'name': name, 'pid': process.pid, 'identity': identity})
    atomic_json(root / 'control/runtime-services.json', {'services': owned})


def recover(root):
    path = root / 'control/runtime-services.json'
    if not path.exists():
        return
    if path.is_symlink():
        raise ValueError('Unsafe service ownership record')
    data = json.loads(path.read_text())
    remaining = []
    for service in data.get('services', []):
        pid = service.get('pid')
        if type(pid) is not int or pid < 1:
            raise ValueError('Invalid process ownership record')
        current = fingerprint(pid)
        if not current:
            continue
        if current != service.get('identity') or str(root) not in current or os.getpgid(pid) != pid:
            continue  # PID reuse or external services never authorize a kill.
        # Popen cannot attach to an orphan. Signal its recorded process group
        # and wait for the private port to close on the next normal startup.
        os.killpg(pid, signal.SIGTERM)
        remaining.append(service)
    if remaining:
        atomic_json(path, {'services': remaining})
    else:
        path.unlink(missing_ok=True)


def publish_runtime(root):
    atomic_json(root / 'control/runtime-owner.json', {'pid': os.getpid(), 'identity': fingerprint(os.getpid())})


def stop(root):
    path = root / 'control/runtime-owner.json'
    if path.is_symlink():
        raise ValueError('Unsafe runtime owner record')
    record = json.loads(path.read_text())
    pid = record.get('pid')
    if type(pid) is not int or pid < 1 or str(root) not in record.get('identity', '') or fingerprint(pid) != record['identity']:
        raise RuntimeError('Recorded Local AI supervisor is unavailable; no process stopped')
    os.kill(pid, signal.SIGTERM)
    print('Graceful shutdown requested. Active work releases its models before exit.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    stop(args.root.resolve(strict=True))
