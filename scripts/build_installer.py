"""Build or verify the sole deployable installer against its source contents."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile

RELEASE = '2026-10-19-village-infrastructure-preview'
PREFIX = 'mac-local-ai-installer/'
STAMP = (2026, 10, 19, 0, 0, 0)


def contents(root):
    result = {}
    for folder, prefix in ((root / 'installer', ''), (root / 'docs', 'docs/')):
        for path in sorted(folder.rglob('*')):
            relative = path.relative_to(folder)
            if '__pycache__' in relative.parts or any(p.startswith('.') for p in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError('Installer source contains a symlink: ' + str(relative))
            if not path.is_file() or path.suffix in {'.pyc', '.pyo'} or relative.as_posix() == 'RELEASE.json':
                continue
            name = prefix + relative.as_posix()
            result[name] = (path.read_bytes(), 0o755 if path.suffix == '.command' else 0o644)
    if not result:
        raise ValueError('Installer source is empty')
    manifest = {'release': RELEASE, 'source_inputs': {
        'main': 'cc490411940f5387191f5127ff853309b857a1e0',
        'required_capabilities': 'bb68a8e101b39d8489b015daecb0c40ba2b040b1',
        'scoped_automation': 'b3439a7938811f4ec8efb98155fd953f35f83d4e'},
        'captain_inputs': {'base': 'ceb8ce6bcb229042b1cf957d974e2838616c6030',
                           'native_runtime': '1b70350c92563449576bcbbf552994b1d1ed847d'},
        'owner_mac_acceptance': 'not_run',
        'village_inputs': {'base': '3694f2935d18609ed9e6e78e7f5834b38f5f92e1', 'facilities_schema': 1},
        'files': {name: hashlib.sha256(data).hexdigest() for name, (data, _) in sorted(result.items())}}
    encoded = json.dumps(manifest, sort_keys=True, indent=2).encode() + b'\n'
    result['RELEASE.json'] = (encoded, 0o644)
    return result


def build(root, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.zip.new')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, (data, mode) in sorted(contents(root).items()):
                info = zipfile.ZipInfo(PREFIX + name, STAMP)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        verify(root, temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def verify(root, archive_path):
    expected = {PREFIX + name: value for name, value in contents(root).items()}
    with zipfile.ZipFile(archive_path) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Installer contains duplicate paths')
        if set(archive.namelist()) != set(expected):
            raise ValueError('Installer/source file manifest differs')
        for name, (data, mode) in expected.items():
            if archive.read(name) != data:
                raise ValueError('Installer differs from source: ' + name)
            if archive.getinfo(name).external_attr >> 16 & 0o777 != mode:
                raise ValueError('Installer file permissions differ: ' + name)
        if archive.testzip() is not None:
            raise ValueError('Installer ZIP integrity check failed')
    print('Verified installer contents, permissions and release manifest.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output or root / 'downloads/Mac-Local-AI-Automated-Installer.zip'
    if args.check:
        verify(root, output)
    else:
        build(root, output)


if __name__ == '__main__':
    main()
