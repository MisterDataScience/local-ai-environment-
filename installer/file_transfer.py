"""User-controlled, explicit staging between browser downloads and work projects.

No arbitrary source tree traversal or implicit access to the encrypted vault.
"""
import argparse
import os
from pathlib import Path
import shutil
import tempfile
import uuid

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


def transfer(root, project_id, filename, *, direction="import"):
    root = Path(root).resolve(strict=True)
    if not isinstance(project_id, str) or len(project_id) != 32 or any(x not in "0123456789abcdef" for x in project_id):
        raise ValueError("Project must be its 32-character local session identifier")
    project = root / "work-agent/projects" / project_id
    if not project.is_dir() or project.is_symlink():
        raise ValueError("Project not found")
    browser = root / "web/browser-outputs"
    if not browser.is_dir() or browser.is_symlink():
        raise ValueError("Browser download directory is unavailable")
    if direction == "import":
        source = contained(browser, filename)
        destination_root = project / "Inbox"
    elif direction == "export":
        source = contained(project, filename)
        destination_root = browser / "Export"
    else:
        raise ValueError("Use import or export")
    if source.suffix.lower() not in EXTENSIONS or not source.is_file():
        raise ValueError("Unsupported file type")
    if source.stat().st_nlink != 1 or source.stat().st_size > MAX_BYTES:
        raise ValueError("File exceeds 50 MB")
    destination_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination_root.is_symlink() or not destination_root.resolve().is_relative_to(project if direction == "import" else browser):
        raise ValueError("Destination directory is unsafe")
    destination = destination_root / source.name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Destination exists; nothing was overwritten")
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        stat = os.fstat(fd)
        if not os.path.isfile(source) or stat.st_nlink != 1 or stat.st_size > MAX_BYTES or not os.path.samestat(stat, os.stat(source, follow_symlinks=False)):
            raise ValueError("Source changed during inspection")
        temp = destination_root / ("." + uuid.uuid4().hex + ".partial")
        out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(out, "wb") as target, os.fdopen(os.dup(fd), "rb") as data:
                shutil.copyfileobj(data, target, 1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            os.link(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
    finally:
        os.close(fd)
    return destination


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
