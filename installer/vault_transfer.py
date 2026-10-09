"""User-invoked file transfer across the mounted Cryptomator vault boundary.

Transfer never unlocks the vault. Import creates a PLAINTEXT copy in the Work
Agent project. Export writes only to vault Outputs; never silently overwrite.
"""
import os
from pathlib import Path
import stat
import uuid

from vault_tools import mounted_root, directory, parts
from file_transfer import EXTENSIONS, MAX_BYTES, contained, project_path, open_source, audit


def same_mount(config, original_fd):
    with mounted_root(config) as current:
        before, after = os.fstat(original_fd), os.fstat(current)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise RuntimeError('Vault mount changed during transfer; no fallback used')


def copy_new(source_fd, dest_fd, name, check_mount=None):
    name = str(name)
    if not name or '/' in name or name in {'.', '..'} or Path(name).suffix.lower() not in EXTENSIONS:
        raise ValueError("Unsupported transfer filename")
    original = os.fstat(source_fd)
    if not stat.S_ISREG(original.st_mode) or original.st_nlink != 1 or original.st_size > MAX_BYTES:
        raise ValueError("Only one regular file under 50 MB may be transferred")
    temp = '.local-ai-transfer-' + uuid.uuid4().hex
    new_file = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dest_fd)
    try:
        with os.fdopen(new_file, 'wb') as target:
            copied = 0
            while True:
                if check_mount:
                    check_mount()
                data = os.read(source_fd, 1_048_576)
                if not data:
                    break
                copied += len(data)
                if copied > MAX_BYTES:
                    raise ValueError('Source grew beyond the transfer budget')
                target.write(data)
            target.flush()
            os.fsync(target.fileno())
        after = os.fstat(source_fd)
        if (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns) != (
                original.st_ino, original.st_dev, original.st_size, original.st_mtime_ns):
            raise ValueError("Source changed during transfer")
        # Atomic link means create-only; an existing target is NEVER replaced.
        if check_mount:
            check_mount()
        os.link(temp, name, src_dir_fd=dest_fd, dst_dir_fd=dest_fd, follow_symlinks=False)
    finally:
        os.unlink(temp, dir_fd=dest_fd)


def transfer_vault(config, root, project_id, name, direction):
    root = Path(root).resolve(strict=True)
    project_path(root, project_id)
    operation = uuid.uuid4().hex
    audit(root, {'id': operation, 'project': project_id, 'direction': direction, 'status': 'started'})
    try:
        result = _transfer_vault(config, root, project_id, name, direction)
        audit(root, {'id': operation, 'project': project_id, 'direction': direction, 'status': 'completed'})
        return result
    except Exception:
        audit(root, {'id': operation, 'project': project_id, 'direction': direction, 'status': 'failed-or-needs-review'})
        raise


def _transfer_vault(config, root, project_id, name, direction):
    root = Path(root).resolve(strict=True)
    project = project_path(root, project_id)
    if (not isinstance(project_id, str) or len(project_id) != 32 or
        any(x not in '0123456789abcdef' for x in project_id) or
        not project.is_dir() or project.is_symlink()):
        raise ValueError("Unknown project session")
    if direction not in {'vault-import', 'vault-export'}:
        raise ValueError("Expected vault-import or vault-export")
    if direction == 'vault-import':
        source_parts = parts(name)
        if len(source_parts) < 2 or Path(source_parts[-1]).suffix.lower() not in EXTENSIONS:
            raise ValueError("Specify a file inside a vault folder")
        inbox = project / 'Inbox'
        inbox.mkdir(mode=0o700, exist_ok=True)
        if inbox.is_symlink() or not inbox.resolve().is_relative_to(project.resolve()):
            raise ValueError("Unsafe project Inbox")
        destination_fd = os.open(inbox, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with mounted_root(config) as vault, directory(vault, source_parts[:-1]) as folder:
                source_fd = os.open(source_parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                    dir_fd=folder)
                try:
                    copy_new(source_fd, destination_fd, source_parts[-1], lambda: same_mount(config, vault))
                finally:
                    os.close(source_fd)
        finally:
            os.close(destination_fd)
        return str(inbox / source_parts[-1]) + ' (PLAINTEXT copy)'
    # Export accepts only a local source inside the active project copy.
    source = contained(project, name)
    if source.suffix.lower() not in EXTENSIONS or not source.is_file():
        raise ValueError("Unsupported local project file")
    source_fd = open_source(project, name)
    try:
        with mounted_root(config) as vault, directory(vault, ['Outputs']) as destination_fd:
            copy_new(source_fd, destination_fd, source.name, lambda: same_mount(config, vault))
    finally:
        os.close(source_fd)
    return 'Outputs/' + source.name + ' (encrypted workspace)'

