"""Complete Cryptomator workspace registration during Captain installation.

Cryptomator's GUI owns vault creation, passwords, recovery keys and unlock.
This helper handles mount discovery, explicit owner confirmation, registration and
a real read/write smoke test while the encrypted volume is mounted. It never
creates a substitute plaintext directory, manages encryption keys or saves them.
"""
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess

from vault_tools import directory, execute, mounted_root


VAULT_NAME = 'AI Workspace'
ICLOUD_DIR = Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs'


def mounted_volumes():
    """Locate actual top-level macOS mounts, not similarly named local folders."""
    candidates = []
    for base in (Path('/Volumes'), Path.home() / 'Cryptomator'):
        if not base.is_dir() or base.is_symlink():
            continue
        for path in base.iterdir():
            try:
                if (path.is_symlink() or not path.is_dir() or path.resolve() != path
                        or not os.path.ismount(path)
                        or path.stat().st_dev == path.parent.stat().st_dev):
                    continue
            except OSError:
                continue
            candidates.append(path)
    return sorted(set(candidates), key=str)


def verify_workspace(config):
    """Exercise the actual guarded workspace tools against the mounted volume."""
    with mounted_root(config):
        pass
    filename = '.local-ai-setup-' + secrets.token_hex(12) + '.txt'
    relative = 'Outputs/' + filename
    content = 'LOCAL AI encrypted workspace installation test ' + secrets.token_hex(10)
    created = False
    try:
        result = execute(config, 'workspace_write', {
            'path': relative, 'content': content, 'expected_sha256': ''})
        created = True
        read = execute(config, 'workspace_read', {'path': relative})
        if read.get('content') != content or read.get('sha256') != result.get('sha256'):
            raise RuntimeError('Encrypted workspace read/write verification failed')
    finally:
        if created:
            with mounted_root(config) as root_fd, directory(root_fd, ['Outputs']) as out_fd:
                os.unlink(filename, dir_fd=out_fd)
    return {'status': 'passed', 'mount_checked': True,
            'workspace_write_read_cleanup': 'passed', 'automatic_unlock': False}


def choose_mount(before, after, prompt, say):
    """Suggest only a named mounted volume; never adopt an arbitrary drive."""
    named = [p for p in after if p.name.casefold() == VAULT_NAME.casefold()]
    fresh = [p for p in named if p not in before]
    suggested = fresh or named
    if len(suggested) == 1:
        mount = suggested[0]
        say('Detected mounted volume: ' + str(mount))
        say('Confirm ONLY if this is the unlocked drive displayed in Cryptomator.')
        if prompt('Is this your unlocked Cryptomator AI Workspace? Type YES: ').strip() != 'YES':
            raise RuntimeError('Cryptomator volume was not confirmed. No vault was registered.')
        return mount
    if len(suggested) > 1:
        say('Multiple matching mounts found. Select the unlocked drive in Cryptomator.')
        for path in suggested:
            say('  ' + str(path))
    else:
        say('No mounted volume named AI Workspace was detected.')
        say('In Cryptomator select Reveal Drive and drag the unlocked volume into Terminal.')
    raw = prompt('Unlocked Cryptomator volume path (not its encrypted iCloud folder): ').strip()
    if not raw:
        raise RuntimeError('No decrypted Cryptomator volume selected. Rerun the installer after unlocking it.')
    # Finder drag-and-drop to Terminal escapes spaces (AI\\ Workspace).
    # Accept a single safely parsed path, never execute shell code.
    try:
        parsed = shlex.split(raw)
    except ValueError:
        raise RuntimeError('Invalid quoted volume path. Supply one mounted path.') from None
    if len(parsed) != 1:
        raise RuntimeError('Supply exactly one mounted volume path.')
    mount = Path(parsed[0]).expanduser().absolute()
    # Cryptomator can use an owner-selected mount location outside /Volumes
    # and ~/Cryptomator. The base-directory scan is only for suggestions.
    # Still require a real separate filesystem and no symlink traversal.
    try:
        valid = (mount.is_dir() and not mount.is_symlink() and mount.resolve() == mount
                 and os.path.ismount(mount) and mount.stat().st_dev != mount.parent.stat().st_dev)
    except OSError:
        valid = False
    if not valid:
        raise RuntimeError('That path is not a verified separate macOS mounted volume. No vault was registered.')
    if prompt('Confirm this is the unlocked Cryptomator drive. Type YES: ').strip() != 'YES':
        raise RuntimeError('Cryptomator volume was not confirmed. No vault was registered.')
    return mount


def configure_during_install(root, app, *, prompt=input, say=print):
    """Finish initial workspace setup during the installer, not after startup.

    Existing configured vaults are never re-created or silently replaced. If the
    saved mount is locked, open Cryptomator for the owner to unlock it.
    """
    root = Path(root)
    path = root / 'control/config.json'
    config = json.loads(path.read_text())
    current = config.get('vault', {})
    if current.get('enabled'):
        try:
            result = verify_workspace(config)
            result['registration'] = 'existing_verified'
            return config, result
        except (OSError, RuntimeError, ValueError) as error:
            say('The existing AI Workspace must be unlocked before native installation tests.')
            say('Cryptomator will open. Unlock the SAME existing vault, then click Reveal Drive.')
            say('No new vault will be created or adopted automatically.')
            say('Current check: ' + str(error))
            subprocess.run(['/usr/bin/open', '-a', str(app)], check=True)
            prompt('Press Enter after the existing encrypted vault is unlocked: ')
            # A mismatched mounted volume must NEVER replace an existing vault ID.
            result = verify_workspace(config)
            result['registration'] = 'existing_unlocked'
            return config, result

    say('')
    say('LOCAL AI encrypted workspace setup: one-time step INSIDE installation.')
    say('Cryptomator will create and unlock the encrypted volume; the installer will')
    say('register it automatically and verify protected file operations.')
    if ICLOUD_DIR.is_dir() and not ICLOUD_DIR.is_symlink():
        say('Choose iCloud Drive as the encrypted vault storage location in Cryptomator.')
    else:
        say('iCloud Drive is not available at its usual location.')
        say('Sign into iCloud Drive in macOS before choosing the vault storage location.')
        say('Do not choose an ordinary local folder if you expect iCloud syncing.')
    say('In Cryptomator: Create New Vault -> name it AI Workspace -> choose iCloud Drive.')
    say('Choose your own password INSIDE Cryptomator; record the recovery key privately.')
    say('Leave Remember Password / automatic unlock OFF. Unlock and click Reveal Drive.')
    say('The installer never reads your password or recovery key.')
    before = set(mounted_volumes())
    subprocess.run(['/usr/bin/open', '-a', str(app)], check=True)
    prompt('Press Enter once AI Workspace is created, UNLOCKED and revealed: ')
    from workspace_setup import register
    mount = choose_mount(before, set(mounted_volumes()), prompt, say)
    config = register(root, mount)
    result = verify_workspace(config)
    result['registration'] = 'created_or_selected_during_install'
    say('Encrypted workspace registered. Inbox, Projects, Outputs and Archive are ready.')
    say('Unlock this vault in Cryptomator after future logins; no password is stored.')
    return config, result
