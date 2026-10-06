"""One-time vault registration. Never requests or stores a vault password."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import uuid

VERSION = '1.19.3'
DMG_SHA256 = '0bfe8c6aeb97acf638810e3e576016db510bc7bf71366dc00f3c7eea9a314f23'
URL = f'https://github.com/cryptomator/cryptomator/releases/download/{VERSION}/Cryptomator-{VERSION}-arm64.dmg'


def save_config(root, config):
    path = root / 'control/config.json'
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.config-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(config, f, indent=2)
            f.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def install_cryptomator(root, download, run):
    # Preserve an existing installation; never change its vaults or preferences.
    for app in (Path('/Applications/Cryptomator.app'), Path.home() / 'Applications/Cryptomator.app', root / 'tools/Cryptomator.app'):
        if app.is_dir():
            run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])
            run(['/usr/sbin/spctl', '--assess', '--type', 'execute', app])
            return app
    archive = root / 'cache' / f'Cryptomator-{VERSION}-arm64.dmg'
    download(URL, archive, DMG_SHA256)
    with tempfile.TemporaryDirectory(dir=root / 'cache') as directory:
        mounted = Path(directory) / 'image'
        run(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', mounted, archive])
        try:
            source = mounted / 'Cryptomator.app'
            run(['/usr/bin/codesign', '--verify', '--deep', '--strict', source])
            run(['/usr/sbin/spctl', '--assess', '--type', 'execute', source])
            target = root / 'tools/Cryptomator.app'
            run(['/usr/bin/ditto', source, target])
            return target
        finally:
            run(['/usr/bin/hdiutil', 'detach', mounted])


def register(root, mount):
    from vault_tools import MARKER, FOLDERS, mounted_root, DIR_FLAGS
    raw = Path(mount).expanduser().absolute()
    if raw.resolve() != raw or not os.path.ismount(raw) or raw.stat().st_dev == raw.parent.stat().st_dev:
        raise ValueError('Select the ROOT of the unlocked Cryptomator volume, not its encrypted iCloud folder or an ordinary directory.')
    config = json.loads((root / 'control/config.json').read_text())
    fd = os.open(raw, DIR_FLAGS)
    try:
        try:
            marker = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            identifier = str(uuid.uuid4())
            marker = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(marker, 'w') as f:
                f.write(identifier)
        else:
            import stat
            with os.fdopen(marker, 'r') as f:
                if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                    raise ValueError('Invalid vault marker.')
                identifier = str(uuid.UUID(f.read(256)))
        candidate = dict(config, vault={'enabled': True, 'mount_path': str(raw), 'id': identifier,
            'manual_unlock': True, 'save_password': False, 'media_policy': 'blocked'})
        with mounted_root(candidate) as checked:
            for folder in FOLDERS:
                try:
                    os.mkdir(folder, mode=0o700, dir_fd=checked)
                except FileExistsError:
                    pass
                child = os.open(folder, DIR_FLAGS, dir_fd=checked)
                os.close(child)
        save_config(root, candidate)
    finally:
        os.close(fd)
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    from common import port_open, PORTS
    if any(port_open(port) for port in PORTS.values()):
        raise SystemExit('Stop Local AI before changing workspace configuration.')
    settings = root / 'control/config.json'
    config = json.loads(settings.read_text())
    app = Path(config['cryptomator_app'])
    subprocess.run(['/usr/bin/open', app], check=True)
    print('In Cryptomator: create AI Workspace inside iCloud Drive, or unlock your existing vault.')
    print('Use a separate password. Leave Remember password and automatic unlocking OFF.')
    print('Keep your recovery key separately. Never enter either secret into this installer or chat.')
    print('Keep the encrypted iCloud folder downloaded on this Mac. Use a mounted-volume backend.')
    print('Click Reveal Drive. Supply that unlocked VOLUME ROOT below, not the encrypted folder.')
    mount = input('Unlocked volume path (blank to finish later): ').strip()
    if not mount:
        print('Workspace remains unavailable until configured. Run this helper again when ready.')
        return
    register(root, mount)
    print('Registered. Restart Local AI, enable Encrypted AI Workspace in chat Integrations, and use Ask for approval.')
    print('Media generation is blocked in vault mode until its temporary/output storage is migrated and verified.')
    print('Chat history and uploads remain in local Open WebUI storage, outside the vault.')


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'payload'))
    main()
