"""User-invoked file transfer across the mounted Cryptomator vault boundary.

Transfer never unlocks the vault. Import creates a PLAINTEXT copy in the Work
Agent project. Export writes only to vault Outputs; never silently overwrite.
"""
import ctypes
import errno
import os
from pathlib import Path
import stat
import sys
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
    temp_exists = True
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
        if check_mount:
            check_mount()
        try:
            os.link(temp, name, src_dir_fd=dest_fd, dst_dir_fd=dest_fd, follow_symlinks=False)
        except OSError as error:
            if error.errno not in _UNSUPPORTED_EXCLUSIVE_OPS:
                raise
            # Cryptomator's mounted volume may not implement hard links. Prefer
            # an atomic no-replace rename; fall back to an exclusive create-copy
            # on filesystems that support neither operation.
            if _rename_exclusive(temp, name, dest_fd):
                temp_exists = False
            else:
                _exclusive_create_copy(temp, name, dest_fd, check_mount)
    finally:
        if temp_exists:
            try:
                os.unlink(temp, dir_fd=dest_fd)
            except FileNotFoundError:
                pass



_UNSUPPORTED_EXCLUSIVE_OPS = {
    errno.ENOTSUP,
    getattr(errno, 'EOPNOTSUPP', errno.ENOTSUP),
    errno.EINVAL,
    getattr(errno, 'ENOSYS', errno.ENOTSUP),
}


def _rename_exclusive(temp, name, dest_fd):
    """Atomically publish a staged file on macOS filesystems that support it."""
    if sys.platform != 'darwin':
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameatx_np = libc.renameatx_np
    except (AttributeError, OSError):
        return False
    renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                             ctypes.c_char_p, ctypes.c_uint]
    renameatx_np.restype = ctypes.c_int
    # Darwin's RENAME_EXCL flag makes the destination check and rename atomic.
    if renameatx_np(dest_fd, os.fsencode(temp), dest_fd, os.fsencode(name), 0x4) == 0:
        return True
    code = ctypes.get_errno()
    if code in _UNSUPPORTED_EXCLUSIVE_OPS:
        return False
    raise OSError(code, os.strerror(code), name)


def _exclusive_create_copy(temp, name, dest_fd, check_mount=None):
    """Copy to an O_EXCL destination when the mounted filesystem rejects links."""
    temp_fd = os.open(temp, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dest_fd)
    target_fd = None
    target_identity = None
    try:
        target_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600, dir_fd=dest_fd)
        info = os.fstat(target_fd)
        target_identity = (info.st_dev, info.st_ino)
        with os.fdopen(target_fd, 'wb') as target:
            target_fd = None
            while True:
                if check_mount:
                    check_mount()
                data = os.read(temp_fd, 1_048_576)
                if not data:
                    break
                target.write(data)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        if target_fd is not None:
            os.close(target_fd)
        if target_identity is not None:
            try:
                current = os.stat(name, dir_fd=dest_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == target_identity:
                    os.unlink(name, dir_fd=dest_fd)
            except OSError:
                pass
        raise
    finally:
        os.close(temp_fd)

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


