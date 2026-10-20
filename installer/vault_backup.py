"""Quiesced Open WebUI backups and legacy archives written directly into the vault."""
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile
import re
import shutil
import uuid

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'payload'))
from vault_tools import DIR_FLAGS, enabled, mounted_root, directory
from vault_media import atomic_output, same_mount, output_directory, MEDIA_NAME


def archive_tree(zipped, source, prefix, config, vault_fd):
    """Walk source using descriptors; never follow file or directory symlinks."""
    entries = []
    def walk(fd, relative):
        for name in sorted(os.listdir(fd)):
            s = os.stat(name, dir_fd=fd, follow_symlinks=False)
            item = relative + '/' + name
            if item.startswith(('village/jobs/upload-','village/jobs/studio-upload-')) or (item.startswith('village/archive/') and item.endswith('.partial')):
                continue  # Incomplete uploads/import copies are not accepted archived sources.
            if item == 'webui-data/cache':
                continue  # Rebuildable model/cache files may include Hugging Face symlinks.
            if stat.S_ISLNK(s.st_mode):
                raise ValueError('Backup source contains a symlink: ' + item)
            if stat.S_ISDIR(s.st_mode):
                child = os.open(name, DIR_FLAGS, dir_fd=fd)
                try:
                    walk(child, item)
                finally:
                    os.close(child)
            elif stat.S_ISREG(s.st_mode):
                file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(file_fd, 'rb') as data:
                    before = os.fstat(data.fileno())
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                        raise ValueError('Backup requires regular single-link files: ' + item)
                    digest = hashlib.sha256()
                    info = zipfile.ZipInfo(item)
                    info.external_attr = 0o100600 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    with zipped.open(info, 'w', force_zip64=True) as dest:
                        while True:
                            same_mount(config, vault_fd)
                            block = data.read(1024 * 1024)
                            if not block:
                                break
                            digest.update(block)
                            dest.write(block)
                    after = os.fstat(data.fileno())
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise RuntimeError('Backup source changed. Stop all writers and retry.')
                    entries.append({'path': item, 'size': after.st_size, 'sha256': digest.hexdigest()})
            else:
                raise ValueError('Unsupported special file in backup: ' + item)
    if source.is_symlink():
        raise ValueError('Backup source must not be a symlink')
    if source.exists():
        fd = os.open(source, DIR_FLAGS)
        try:
            walk(fd, prefix)
        finally:
            os.close(fd)
    return entries


def snapshot(root,config,legacy=False):
    from village_storage import offline_access
    with offline_access(root):return _snapshot(root,config,legacy)


def _snapshot(root, config, legacy=False):
    """Caller MUST hold runtime/gateway locks with services stopped."""
    if not enabled(config):
        return None
    from common import PORTS, port_open
    # Never take an inconsistent copy, even if called outside the normal launcher.
    if (any(port_open(PORTS[k]) for k in ('webui', 'gateway', 'comfy')) or port_open(4096)):
        raise RuntimeError('Stop Local AI before backing up its data.')
    sources = [(root / 'webui/data', 'webui-data')]
    from village_storage import inventory,sync_ledger
    if (root/'village-deletion-pending.json').exists():raise RuntimeError('Resume pending source deletion before backup')
    if (root/'village').exists():
        sync_ledger(root,config)
        sources.append((root/'village','village'))
    if legacy:
        sources += [(root / 'control/media', 'legacy/gateway-media'),
                    (root / 'ComfyUI/output', 'legacy/comfy-output'),
                    (root / 'ComfyUI/temp', 'legacy/comfy-temp'),
                    (root / 'logs', 'legacy/logs'), (root / 'control/logs', 'legacy/control-logs')]
    if not any(p.exists() and any(p.iterdir()) for p, _ in sources):
        return None
    with atomic_output(config, '.zip', 'Migration' if legacy else 'Backups') as (out, name, vault_fd):
        with zipfile.ZipFile(out, 'w', allowZip64=True) as zipped:
            entries = []
            for source, prefix in sources:
                entries.extend(archive_tree(zipped, source, prefix, config, vault_fd))
            # Keep the stable key needed to decrypt WebUI OAuth records on restore.
            # The separate GitHub PAT and vault password are NOT included.
            zipped.writestr('restore-settings.json', json.dumps({
                'webui_secret': config.get('webui_secret'), 'text_models': config.get('text_models')}, indent=2))
            zipped.writestr('manifest.json', json.dumps({'format': 2, 'village_sources': inventory(root),
                'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'method': 'offline-copy-including-sqlite-wal', 'files': entries,
                'excluded': ['webui-data/cache','village/jobs/upload-*','village/archive/*.partial'],
                'legacy_sources_preserved': bool(legacy)}, indent=2))
    if not legacy:
        retain_backups(config, name)
    return ('Archive/Migration/' if legacy else 'Archive/Backups/') + name


def migrate_media(root, config):
    """Preserve old generated UUID URLs; copy only, never remove source files."""
    source = root / 'control/media'
    if not source.exists():
        return 0
    if source.is_symlink():
        raise ValueError('Legacy media directory must not be a symlink')
    count = 0
    src_fd = os.open(source, DIR_FLAGS)
    try:
        with output_directory(config) as (vault_fd, dest_fd):
            for name in os.listdir(src_fd):
                if not MEDIA_NAME.fullmatch(name):
                    continue  # Non-generated names are retained in the migration archive.
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=src_fd)
                with os.fdopen(fd, 'rb') as src:
                    info = os.fstat(src.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ValueError('Legacy media must be regular single-link files')
                    try:
                        output_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dest_fd)
                    except FileExistsError:
                        # Never overwrite a vault file on a repeated migration.
                        continue
                    try:
                        with os.fdopen(output_fd, 'wb') as dst:
                            while True:
                                same_mount(config, vault_fd)
                                block = src.read(1024 * 1024)
                                if not block:
                                    break
                                dst.write(block)
                            dst.flush()
                            os.fsync(dst.fileno())
                        after = os.fstat(src.fileno())
                        if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            raise RuntimeError('Legacy media changed during migration')
                        same_mount(config, vault_fd)
                        count += 1
                    except Exception:
                        os.unlink(name, dir_fd=dest_fd)
                        raise
    finally:
        os.close(src_fd)
    return count


def retain_backups(config, newest):
    """Retain the new snapshot and two most recent generated backup archives."""
    with output_directory(config, 'Backups') as (vault_fd, folder):
        candidates = []
        for name in os.listdir(folder):
            if re.fullmatch(r'[0-9a-f]{32}\.zip', name) and name != newest:
                info = os.stat(name, dir_fd=folder, follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    candidates.append((info.st_mtime_ns, name))
        for _, name in sorted(candidates, reverse=True)[2:]:
            same_mount(config, vault_fd)
            os.unlink(name, dir_fd=folder)


def restore(root,config,relative):
    from village_storage import offline_access
    with offline_access(root):return _restore(root,config,relative)


def _restore(root, config, relative):
    if (root/'village-deletion-pending.json').exists():raise RuntimeError('Resume pending source deletion before restore')
    """Restore offline to a new local directory, preserving the previous data."""
    from common import PORTS, port_open
    if (any(port_open(PORTS[k]) for k in ('webui', 'gateway', 'comfy')) or port_open(4096)):
        raise RuntimeError('Stop Local AI before restoring.')
    if not re.fullmatch(r'Archive/(Backups|Migration)/[0-9a-f]{32}\.zip', relative):
        raise ValueError('Choose an archive path printed by the backup helper.')
    data = root / 'webui/data'
    if data.is_symlink() or data.parent.resolve() != data.parent:
        raise ValueError('WebUI data paths must not be symlinks')
    stage = root / 'webui' / ('.restore-' + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    village_stage=root/('.village-restore-'+uuid.uuid4().hex)
    village_stage.mkdir(mode=0o700)
    village_previous=root/('village.before-restore-'+uuid.uuid4().hex)
    village_moved=False;village_installed=False;has_village=False;has_webui=False;webui_installed=False
    previous = root / 'webui' / ('data.before-restore-' + uuid.uuid4().hex)
    moved = False
    try:
        with mounted_root(config) as vault_fd:
            parts = relative.split('/')
            with directory(vault_fd, parts[:-1]) as folder:
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
                with os.fdopen(fd, 'rb') as source:
                    info = os.fstat(source.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ValueError('Archive must be a regular single-link file')
                    with zipfile.ZipFile(source) as zipped:
                        if len(zipped.namelist()) != len(set(zipped.namelist())):
                            raise ValueError('Duplicate archive entries')
                        manifest = json.loads(zipped.read('manifest.json'))
                        if manifest.get('format') not in (1,2):
                            raise ValueError('Unsupported backup format')
                        if any(e['path'].startswith('village/') for e in manifest['files']):
                            from village_storage import guard_restore
                            guard_restore(root,config,manifest)
                        entries=manifest.get('files')
                        if not isinstance(entries,list) or len(entries)>100000 or any(type(e.get('size')) is not int or not 0<=e['size']<=8*1024**3 for e in entries) or sum(e['size'] for e in entries)>64*1024**3:raise ValueError('Backup exceeds restore bounds')
                        settings = json.loads(zipped.read('restore-settings.json'))
                        seen = set()
                        for entry in manifest['files']:
                            path = entry['path']
                            if not path.startswith(('webui-data/','village/')):
                                continue  # Legacy archives remain archives; never overwrite media/logs.
                            parts = path.split('/')[1:]
                            if not parts or any(p in ('', '.', '..') or '\\' in p for p in parts) or path in seen:
                                raise ValueError('Invalid backup path')
                            seen.add(path)
                            is_village=path.startswith('village/')
                            has_village=has_village or is_village
                            has_webui=has_webui or not is_village
                            target = (village_stage if is_village else stage).joinpath(*parts)
                            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                            digest, size = hashlib.sha256(), 0
                            with zipped.open(path) as src, target.open('xb') as dst:
                                os.chmod(target, 0o600)
                                while True:
                                    same_mount(config, vault_fd)
                                    block = src.read(1024 * 1024)
                                    if not block:
                                        break
                                    size += len(block)
                                    if size>entry['size']:raise ValueError('Backup expands beyond its declared size')
                                    digest.update(block)
                                    dst.write(block)
                            if size != entry['size'] or digest.hexdigest() != entry['sha256']:
                                raise ValueError('Backup checksum mismatch')
                        if not seen:
                            raise ValueError('Archive contains no WebUI data')
                        same_mount(config, vault_fd)
        if has_village:
            from village import secure_root
            secure_root(root/'village')
            from village_storage import validate_restored
            validate_restored(root,config,village_stage)
        if has_webui and data.exists():
            data.rename(previous)
            moved = True
        try:
            if has_webui:stage.rename(data);webui_installed=True
            if has_village:
                (root/'village').rename(village_previous);village_moved=True
                village_stage.rename(root/'village');village_installed=True
            updated = dict(config)
            if settings.get('webui_secret'):
                updated['webui_secret'] = settings['webui_secret']
            from workspace_setup import save_config
            save_config(root, updated)
        except Exception:
            if village_installed:(root/'village').rename(village_stage)
            if village_moved:village_previous.rename(root/'village')
            if webui_installed and data.exists():
                data.rename(stage)
            if moved:
                previous.rename(data)
            raise
        return previous if moved else None
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if village_stage.exists():shutil.rmtree(village_stage)


@contextmanager
def stopped_runtime(root):
    held = []
    try:
        for path in (root / '.runtime.lock', root / 'control/.gateway.lock'):
            f = path.open('a')
            held.append(f)
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Stop Local AI before backup or restore.')
        yield
    finally:
        for f in reversed(held):
            f.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--migrate-legacy', action='store_true')
    modes.add_argument('--restore', metavar='ARCHIVE', nargs='?', const='ASK')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    config = json.loads((root / 'control/config.json').read_text())
    with stopped_runtime(root):
        if args.restore:
            archive = input('Archive path (Archive/Backups/…zip): ').strip() if args.restore == 'ASK' else args.restore
            previous = restore(root, config, archive)
            print('Restored WebUI data. Previous data preserved at ' + str(previous) if previous else 'Restored WebUI data.')
            return
        result = snapshot(root, config, args.migrate_legacy)
        if args.migrate_legacy:
            print('Copied generated media into the vault:', migrate_media(root, config))
    print('Saved ' + result if result else 'No data to back up.')
    if args.migrate_legacy:
        print('Original local files were preserved. Verify the encrypted archive before removing any originals.')


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'payload'))
    main()
