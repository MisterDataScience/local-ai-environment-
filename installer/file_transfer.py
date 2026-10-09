"""User-controlled, explicit staging between browser downloads and work projects.

No arbitrary source tree traversal or implicit access to the encrypted vault.
"""
import argparse
import os
from pathlib import Path
import uuid
import json
import time
import fcntl

MAX_BYTES = 50 * 1024 * 1024
EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".txt", ".md",
              ".png", ".jpg", ".jpeg", ".webp", ".json", ".svg", ".html"}


def contained(root, relative):
    root = Path(root).resolve(strict=True)
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ValueError("Use a relative path inside the chosen source")
    current = root
    for bit in candidate.parts:
        current = current / bit
        if current.is_symlink():
            raise ValueError("Symlinks are not permitted")
    target = current.resolve(strict=True)
    if not target.is_relative_to(root):
        raise ValueError("File escapes source directory")
    return target


def open_source(root, relative):
    """Open every component relative to a trusted descriptor, refusing links."""
    contained(root, relative)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        bits = Path(relative).parts
        for bit in bits[:-1]:
            child = os.open(bit, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return os.open(bits[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)


def project_path(root, project_id):
    if not isinstance(project_id, str) or len(project_id) != 32 or any(x not in '0123456789abcdef' for x in project_id):
        raise ValueError('Invalid project session')
    project = contained(root, 'work-agent/projects/' + project_id)
    if not project.is_dir():
        raise ValueError('Project unavailable')
    return project


def audit(root, record):
    folder = root / 'work-agent/state'
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    if folder.is_symlink() or not folder.resolve().is_relative_to(root):
        raise ValueError('Unsafe transfer ledger')
    fd = os.open(folder / 'transfers.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as out:
        fcntl.flock(out, fcntl.LOCK_EX)
        out.write(json.dumps(dict(record, time=int(time.time()))) + '\n')
        out.flush()
        os.fsync(out.fileno())


def transfer_local(root, project_id, filename, direction):
    root = Path(root).resolve(strict=True)
    project = project_path(root, project_id)
    roots = {'chat-import': root / 'chat-attachments', 'media-import': root / 'control/media',
             'browser-import': root / 'web/browser-outputs', 'browser-export': project}
    if direction not in roots:
        raise ValueError('Unknown transfer direction')
    source_root = roots[direction]
    if not source_root.is_dir() or source_root.is_symlink():
        raise ValueError('Source unavailable')
    source = contained(source_root, filename)
    if source.suffix.lower() not in EXTENSIONS:
        raise ValueError('Unsupported file type')
    destination_root = root / 'web/browser-outputs/Export' if direction == 'browser-export' else project / 'Inbox'
    destination_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    contained(root, destination_root.relative_to(root))
    job = uuid.uuid4().hex
    audit(root, {'id': job, 'project': project_id, 'direction': direction, 'status': 'started'})
    source_fd = open_source(source_root, filename)
    destination_fd = os.open(destination_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        from vault_transfer import copy_new
        # Chat's stable attachment name would collide across uploads. Preserve
        # the immutable upload id in the imported filename instead.
        name = (Path(filename).parts[0] + '-' + source.name) if direction == 'chat-import' else source.name
        copy_new(source_fd, destination_fd, name)
        audit(root, {'id': job, 'project': project_id, 'direction': direction,
                     'status': 'completed', 'name': name, 'bytes': os.fstat(source_fd).st_size})
    except Exception:
        audit(root, {'id': job, 'project': project_id, 'direction': direction, 'status': 'failed-or-needs-review'})
        raise
    finally:
        os.close(source_fd)
        os.close(destination_fd)
    return destination_root / name


def transfer(root, project_id, filename, *, direction="import"):
    if direction not in {'import', 'export'}:
        raise ValueError('Use import or export')
    return transfer_local(root, project_id, filename, 'browser-' + direction)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--direction", choices=("import", "export", "vault-import", "vault-export"), default="import")
    args = parser.parse_args()
    if args.direction.startswith("vault-"):
        import json
        from vault_transfer import transfer_vault
        config = json.loads((args.root.expanduser() / "control/config.json").read_text())
        print(transfer_vault(config, args.root, args.project, args.file, args.direction))
    else:
        print(transfer(args.root, args.project, args.file, direction=args.direction))


if __name__ == "__main__":
    main()

