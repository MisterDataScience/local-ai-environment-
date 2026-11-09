"""Apply the known Captain dispatch repair and run only its native acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


BASELINE = {
    'captain.mjs': '88c40dc6da37e17e9683f5040ab17d5381481ea3f2e91c116d076a5e17942c3e',
    'captain_check.py': 'beba3e0d7d044d919d7fbc7cc063257cb969fb24ae13f467b8b6b919bec42324',
    'acceptance_diagnostics.py': (None, '0cf2c6083512076f6b64b3e21aedd3bac1478f4e8535f787465977bc89eedcb0'),
}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def atomic_bytes(path, content):
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.captain-repair-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply(root, source=None):
    root = Path(root).expanduser().absolute()
    source = Path(source or Path(__file__).resolve().parent)
    sys.path.insert(0, str(root / 'control'))
    from feature_state import installation_lock, safe_path
    from feature_install import ensure_stopped
    manifest = json.loads((source / 'RELEASE.json').read_text())['files']
    prepared = []
    with installation_lock(root):
        ensure_stopped(root)
        # Validate the whole change before writing any installed file.
        for name, expected in BASELINE.items():
            content = (source / name).read_bytes()
            if digest(content) != manifest.get(name):
                raise RuntimeError('Repair source differs from its release manifest: ' + name)
            if name.endswith('.py'):
                compile(content, name, 'exec')
            target = safe_path(root / 'control' / name)
            original = target.read_bytes() if target.exists() else None
            if original == content:
                continue
            allowed = expected if isinstance(expected, tuple) else (expected,)
            if (digest(original) if original is not None else None) not in allowed:
                raise RuntimeError('Installed file differs from the diagnosed version: ' + name)
            backup = safe_path(target.with_name(name + '.before-captain-dispatch-fix'))
            if backup.exists() and (original is None or backup.read_bytes() != original):
                raise RuntimeError('Existing repair backup differs: ' + backup.name)
            prepared.append((target, content, original, backup))
        for target, content, original, backup in prepared:
            if original is not None and not backup.exists():
                # Never overwrite an existing backup, including a symbolic link.
                with backup.open('xb') as stream:
                    os.chmod(backup, 0o600)
                    stream.write(original)
                    stream.flush()
                    os.fsync(stream.fileno())
        changed = []
        try:
            for target, content, original, backup in prepared:
                atomic_bytes(target, content)
                changed.append((target, original))
        except Exception:
            for target, original in reversed(changed):
                if original is None:
                    target.unlink()
                else:
                    atomic_bytes(target, original)
            raise
    return {'status': 'applied' if prepared else 'already_applied',
            'files': [target.name for target, *_ in prepared],
            'backups': [str(backup) for _, _, original, backup in prepared if original is not None]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'LocalAI-Automated')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--apply-only', action='store_true', help='Apply the repair without running inference')
    args = parser.parse_args()
    root = args.root.expanduser().absolute()
    repair = apply(root)
    if args.apply_only:
        print(json.dumps(repair, indent=2))
        return 0
    from acceptance_diagnostics import retry_captain, save, console_summary
    report = retry_captain(root)
    report['repair'] = repair
    path = save(args.output or root / 'logs/native-acceptance/captain-diagnostic.json', report)
    print(json.dumps(console_summary(report, path), ensure_ascii=False, indent=2))
    return 0 if report['probe']['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
