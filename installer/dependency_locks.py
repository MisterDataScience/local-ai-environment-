"""Install only the release's hashed packages into its private environments."""
import hashlib
from pathlib import Path

LOCKS = {
    'control': ('control-macos-arm64-py311.txt', (3, 11)),
    'webui': ('webui-macos-arm64-py311.txt', (3, 11)),
    'voice': ('voice-macos-arm64-py312.txt', (3, 12)),
    'voice-build': ('voice-build-macos-arm64-py312.txt', (3, 12)),
}


def lock_path(name):
    return Path(__file__).resolve().parent / 'locks' / LOCKS[name][0]


def receipt(name):
    result = {'lock_sha256': hashlib.sha256(lock_path(name).read_bytes()).hexdigest(),
              'python': '.'.join(map(str, LOCKS[name][1]))}
    if name == 'voice':
        result['build_lock_sha256'] = receipt('voice-build')['lock_sha256']
    return result


def install_locked(uv, python, name, run):
    """Reconcile even on repeat installs, so stale markers cannot hide drift.

    Only mlx-audio may build, from a hash-checked immutable source archive.
    Its backend is preinstalled from a separate wheel-only hashed lock, and
    build isolation is disabled so the backend cannot resolve more packages.
    """
    major, minor = LOCKS[name][1]
    run([python, '-c', 'import platform, sys; '
         "assert platform.system() == 'Darwin' and platform.machine() == 'arm64'; "
         f'assert sys.version_info[:2] == ({major}, {minor})'])
    if name == 'voice':
        run([uv, 'pip', 'install', '--python', python, '--require-hashes',
             '--only-binary', ':all:', '--no-deps', '-r', lock_path('voice-build')])
    command = [uv, 'pip', 'sync', '--python', python, '--require-hashes',
               '--only-binary', ':all:']
    if name == 'voice':
        command += ['--no-binary', 'mlx-audio', '--no-build-isolation']
    run(command + [lock_path(name)])
    # sync installs the complete lock; check detects a missing transitive edge.
    run([uv, 'pip', 'check', '--python', python])
    return receipt(name)
