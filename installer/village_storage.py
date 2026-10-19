"""Owner-only offline Village recovery and source erasure.

The registered Cryptomator mount provides encryption. Deletion tombstones live
outside restored data and are also replicated into that vault before erasure.
"""
import hashlib
import fcntl
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time

HEX=re.compile(r'^[0-9a-f]{64}$')
LEDGER='village-deletions.json'
PENDING='village-deletion-pending.json'


@contextmanager
def offline_access(root):
    fd=os.open(Path(root)/'.village-store.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Village is busy; stop its writers and retry')
        yield


def _read(path,default):
    if not path.exists():return default
    if path.is_symlink() or path.stat().st_mode&0o077 or path.stat().st_nlink!=1:raise PermissionError('Insecure Village recovery record')
    return json.loads(path.read_text())


def _write(path,value):
    if path.is_symlink():raise ValueError('Recovery record symlink rejected')
    fd,name=tempfile.mkstemp(prefix='.village-write-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:json.dump(value,out,sort_keys=True);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:Path(name).unlink(missing_ok=True)


def ledger(root):
    value=_read(Path(root)/LEDGER,dict(format=1,sources=[],conversations=[]))
    if value.get('format')!=1 or any(not HEX.fullmatch(x) for k in ('sources','conversations') for x in value.get(k,[])):raise ValueError('Invalid deletion ledger')
    return value


def sync_ledger(root,config):
    from vault_tools import mounted_root,directory,read_bytes
    from vault_media import same_mount
    local=ledger(root)
    with mounted_root(config) as vault, directory(vault,['Archive']) as folder:
        try:remote=json.loads(read_bytes(folder,LEDGER))
        except FileNotFoundError:remote=dict(format=1,sources=[],conversations=[])
        if remote.get('format')!=1:raise ValueError('Unsupported vault deletion ledger')
        merged=dict(format=1,**{k:sorted(set(local.get(k,[]))|set(remote.get(k,[]))) for k in ('sources','conversations')})
        if any(not HEX.fullmatch(x) for k in ('sources','conversations') for x in merged[k]):raise ValueError('Invalid vault deletion ledger')
        name='.village-ledger-'+os.urandom(12).hex()
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=folder)
        try:
            with os.fdopen(fd,'wb') as out:out.write(json.dumps(merged,sort_keys=True).encode());out.flush();os.fsync(out.fileno())
            same_mount(config,vault);os.replace(name,LEDGER,src_dir_fd=folder,dst_dir_fd=folder);os.fsync(folder)
        finally:
            try:os.unlink(name,dir_fd=folder)
            except FileNotFoundError:pass
    _write(Path(root)/LEDGER,merged)
    return merged


def inventory(root):
    village=Path(root)/'village';sources=set()
    if village.is_symlink():raise ValueError('Village symlink rejected')
    db=village/'village.sqlite'
    if db.is_symlink():raise ValueError('Village database symlink rejected')
    if db.exists():
        with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as cx:sources.update(r[0] for r in cx.execute('SELECT sha FROM imports'))
    if (village/'archive').exists():
        for p in (village/'archive').iterdir():
            match=re.match(r'^([0-9a-f]{64})(?:\.|$)',p.name)
            if match:sources.add(match.group(1))
    return sorted(sources)


def guard_restore(root,config,manifest):
    blocked=sync_ledger(root,config)
    if set(manifest.get('village_sources',[]))&set(blocked['sources']):raise PermissionError('This backup contains a forgotten source and cannot be restored')
    if blocked['sources'] and any(e['path'].startswith('village/') for e in manifest['files']) and 'village_sources' not in manifest:raise PermissionError('Village backup lacks deletion-safe source inventory')


def validate_restored(root,config,stage):
    blocked=sync_ledger(root,config)
    db=stage/'village.sqlite'
    if not db.exists():raise ValueError('Village backup lacks its database')
    with sqlite3.connect(db) as cx:
        if cx.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Village database integrity check failed')
        if cx.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Village foreign key check failed')
        if {r[0] for r in cx.execute('SELECT sha FROM imports')}&set(blocked['sources']):raise PermissionError('Restored database contains a forgotten source')
        for (cid,) in cx.execute('SELECT id FROM conversations'):
            if hashlib.sha256(cid.encode()).hexdigest() in blocked['conversations']:raise PermissionError('Restored database contains forgotten conversations')
        if cx.execute("SELECT 1 FROM sqlite_master WHERE name='founding_jobs'").fetchone():cx.execute("UPDATE founding_jobs SET state='paused' WHERE state='running'")
    commons=stage/'commons.sqlite'
    if commons.exists():
        with sqlite3.connect(commons) as cx:
            if cx.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Commons backup integrity check failed')
            cx.execute("UPDATE sessions SET state='paused' WHERE state='running'")


def check_import(root,sha,source):
    import village
    installation=Path(root).parent
    config_path=installation/'control/config.json'
    if config_path.exists():
        if config_path.is_symlink():raise ValueError('Unsafe configuration path')
        config=json.loads(config_path.read_text())
        if config.get('vault',{}).get('enabled'):sync_ledger(installation,config)
    blocked=ledger(installation)
    if sha in blocked['sources']:raise PermissionError('This source was forgotten and cannot be reimported')
    if not blocked['conversations']:return
    with Path(source).open(encoding='utf-8') as stream:
        for item in village.objects(stream):
            raw=json.dumps(item,ensure_ascii=False,separators=(',',':'))
            cid=str(item.get('id') or 'missing-'+village.digest(raw.encode())[:24])
            if hashlib.sha256(cid.encode()).hexdigest() in blocked['conversations']:raise PermissionError('The export contains forgotten conversations; remove them before importing')


def deletion_plan(root,config,source_sha):
    import village
    if not isinstance(source_sha,str) or not HEX.fullmatch(source_sha):raise ValueError('Choose an imported source SHA')
    cx=village.connect(Path(root)/'village',maintenance=True)
    try:
        if not cx.execute('SELECT 1 FROM imports WHERE sha=?',(source_sha,)).fetchone() and not (Path(root)/'village/archive'/(source_sha+'.json')).exists():raise ValueError('Unknown imported source')
        cids={r[0] for r in cx.execute('SELECT id FROM conversations WHERE source_sha=?',(source_sha,))}
        raw=Path(root)/'village/archive'/(source_sha+'.json')
        if raw.is_symlink():raise ValueError('Archive symlink rejected')
        corrupt=False
        if raw.exists():
            try:
                with raw.open(encoding='utf-8') as stream:
                    for item in village.objects(stream):
                        text=json.dumps(item,ensure_ascii=False,separators=(',',':'));cids.add(str(item.get('id') or 'missing-'+village.digest(text.encode())[:24]))
            except (ValueError,UnicodeError):corrupt=True
        # Another retained export can contain the same source conversations.
        sources={source_sha}
        if corrupt:
            sources.update(inventory(root));cids.update(r[0] for r in cx.execute('SELECT id FROM conversations'))
        for path in sorted((Path(root)/'village/archive').glob('*.json')):
            if not HEX.fullmatch(path.stem) or path.stem==source_sha:continue
            if path.is_symlink():raise ValueError('Archive symlink rejected')
            try:
                with path.open(encoding='utf-8') as stream:
                    for item in village.objects(stream):
                        text=json.dumps(item,ensure_ascii=False,separators=(',',':'));cid=str(item.get('id') or 'missing-'+village.digest(text.encode())[:24])
                        if cid in cids:sources.add(path.stem);break
            except (ValueError,UnicodeError):sources.add(path.stem)
        sources.update(r[0] for r in cx.execute("SELECT sha FROM imports WHERE filename='Commons approved research snapshot'"))
        available={r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts={table:cx.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('messages','lessons','specialists','library_documents','resident_memories','resident_starting_maps') if table in available}
    finally:cx.close()
    plan=dict(format=1,source=source_sha,corrupt_source_conservative_reset=corrupt,source_copies=sorted(sources),conversation_hashes=sorted(hashlib.sha256(c.encode()).hexdigest() for c in cids),counts=counts,
              effects=['Delete the selected export and overlapping managed export copies','Delete all derived Village Library material, memories, maps, lessons, workshop/practice material and pending reviews because uncited copies cannot be reliably attributed','Remove derived specialists and their stored identities/directions; retain the five baseline roles','Clear Commons/founding caches, retained Village restore copies, native Captain session history, managed project copies and runtime logs','Remove managed workspace backup archives; preserve a deletion ledger that blocks resurrection'],
              outside_scope=['Files copied to external projects/downloads, external backups, and storage-device forensic remnants'])
    # Snapshot the affected live state so a stale preview cannot authorize new data.
    state=[]
    folders=[Path(root)/'village',Path(root)/'work-agent/state',Path(root)/'work-agent/projects',Path(root)/'logs',Path(root)/'control/logs']+list(Path(root).glob('village.before-restore-*'))+list(Path(root).glob('.village-restore-*'))
    for folder in folders:
        if folder.is_symlink():raise ValueError('Deletion target directory is a symlink')
        if folder.exists():
            for p in sorted(folder.rglob('*')):
                if p.is_symlink():raise ValueError('Deletion source contains a symlink')
                if p.is_file():
                    s=p.stat()
                    if s.st_nlink!=1:raise ValueError('Deletion refuses hard-linked managed files')
                    state.append((str(p.relative_to(root)),s.st_size,s.st_mtime_ns))
    plan['state_digest']=hashlib.sha256(json.dumps(state).encode()).hexdigest()
    plan['digest']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    return plan


def erase(root,config,source_sha,digest):
    from common import PORTS,port_open
    if any(port_open(p) for p in (PORTS['webui'],PORTS['gateway'],PORTS['comfy'],4096)):raise RuntimeError('Stop Local AI before source erasure')
    with offline_access(root):return _erase(root,config,source_sha,digest)


def _erase(root,config,source_sha,digest):
    """Called with runtime stopped. Tombstone first, fail closed on interruption."""
    import village
    root=Path(root);pending=root/PENDING
    saved=_read(pending,None)
    if saved:
        if saved['source']!=source_sha or saved['digest']!=digest:raise ValueError('Resume the pending deletion before selecting another source')
        plan=saved
    else:
        plan=deletion_plan(root,config,source_sha)
        if plan['digest']!=digest:raise ValueError('Village changed; review a fresh deletion preview')
        _write(pending,plan)
    value=ledger(root)
    value['sources']=sorted(set(value['sources'])|set(plan['source_copies']))
    value['conversations']=sorted(set(value['conversations'])|set(plan['conversation_hashes']))
    _write(root/LEDGER,value);sync_ledger(root,config)
    # Once the ledger is durable, remove every managed encrypted workspace snapshot.
    from vault_tools import mounted_root,directory
    from vault_media import same_mount
    with mounted_root(config) as vault:
        for category in ('Backups','Migration'):
            try:
                with directory(vault,['Archive',category]) as folder:
                    for name in os.listdir(folder):
                        if re.fullmatch(r'[0-9a-f]{32}\.zip',name):
                            s=os.stat(name,dir_fd=folder,follow_symlinks=False)
                            if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise ValueError('Unsafe managed backup')
                            same_mount(config,vault);os.unlink(name,dir_fd=folder)
                    os.fsync(folder)
            except FileNotFoundError:pass
    cx=village.connect(root/'village',maintenance=True)
    try:
        cx.execute('PRAGMA secure_delete=ON')
        with cx:
            tables={r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            # All derived records are conservatively invalidated; raw unrelated imports remain.
            for table in ('practice_projects','practice_results','practice_cases','facility_entries','workshop_revisions','workshop_items','facility_receipts','resident_changes','resident_change_decisions','resident_starting_map_revisions','resident_starting_maps','resident_memory_revisions','resident_pointers','resident_memories','library_documents','commons_approvals','lessons','proposals','navigation','founding_items','founding_chunks','founding_jobs'):
                if table in tables:cx.execute('DELETE FROM '+table)
            for source in plan['source_copies']:
                cids=[r[0] for r in cx.execute('SELECT id FROM conversations WHERE source_sha=?',(source,))]
                for cid in cids:cx.execute('DELETE FROM messages WHERE conversation_id=?',(cid,));cx.execute('DELETE FROM conversations WHERE id=?',(cid,))
                cx.execute('DELETE FROM imports WHERE sha=?',(source,))
            # Also remove old message revisions belonging to a forgotten conversation.
            for (cid,) in list(cx.execute('SELECT DISTINCT conversation_id FROM messages')):
                if hashlib.sha256(cid.encode()).hexdigest() in plan['conversation_hashes']:cx.execute('DELETE FROM messages WHERE conversation_id=?',(cid,));cx.execute('DELETE FROM conversations WHERE id=?',(cid,))
            cx.execute('DELETE FROM profiles WHERE specialist_id IN (SELECT id FROM specialists WHERE parent_id IS NOT NULL)')
            cx.execute('DELETE FROM grants WHERE specialist_id IN (SELECT id FROM specialists WHERE parent_id IS NOT NULL)')
            while cx.execute('SELECT 1 FROM specialists WHERE parent_id IS NOT NULL').fetchone():
                leaves=[r[0] for r in cx.execute('SELECT s.id FROM specialists s WHERE s.parent_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM specialists c WHERE c.parent_id=s.id)')]
                if not leaves:raise RuntimeError('Invalid specialist lineage during erasure')
                for sid in leaves:cx.execute('DELETE FROM specialists WHERE id=?',(sid,))
            cx.execute("UPDATE profiles SET instruction='',approval='Source erasure'")
            cx.execute("UPDATE specialists SET tags='[]',approval='Source erasure'")
            cx.execute("UPDATE collections SET note=''")
            cx.execute('DELETE FROM audit')
            cx.execute("INSERT INTO message_fts(message_fts) VALUES('delete-all')")
            cx.execute('INSERT INTO message_fts(rowid,text,title) SELECT m.rowid,m.text,c.title FROM messages m JOIN conversations c ON c.id=m.conversation_id')
        cx.execute('PRAGMA wal_checkpoint(TRUNCATE)');cx.execute('VACUUM')
    finally:cx.close()
    for source in plan['source_copies']:(root/'village/archive'/(source+'.json')).unlink(missing_ok=True)
    for name in ('commons.sqlite','commons.sqlite-wal','commons.sqlite-shm'):(root/'village'/name).unlink(missing_ok=True)
    for name in ('jobs','exports','library','practice'):
        p=root/'village'/name
        if p.exists():shutil.rmtree(p)
    for p in list(root.glob('village.before-restore-*'))+list(root.glob('.village-restore-*')):
        if p.is_symlink():raise ValueError('Unsafe retained restore copy')
        if p.is_dir():shutil.rmtree(p)
    for state in (root/'work-agent/state',root/'work-agent/projects',root/'logs',root/'control/logs'):
        if state.exists():shutil.rmtree(state)
    for path in (root/'village/archive').glob('*.partial'):path.unlink()
    pending.unlink();return dict(state='erased',sources=plan['source_copies'],scope='Managed Village data, native Captain history and workspace backup archives; external copies are outside this operation')
