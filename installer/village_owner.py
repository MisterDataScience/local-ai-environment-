"""Owner launchers for encrypted recovery and reviewed, offline source erasure."""
import argparse
import json
from pathlib import Path
import time


def stop_owned(root):
    from common import PORTS,port_open
    if any(port_open(p) for p in (PORTS['gateway'],PORTS['webui'],4096)):
        from service_lifecycle import stop
        stop(root)
        end=time.monotonic()+60
        while any(port_open(p) for p in (PORTS['gateway'],PORTS['webui'],4096)):
            if time.monotonic()>=end:raise RuntimeError('Shutdown is still draining; retry once Local AI stops')
            time.sleep(.25)


def main():
    parser=argparse.ArgumentParser(description='Owner-only Village recovery and forgetting')
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--operation',choices=['backup','restore','forget'],required=True)
    parser.add_argument('--source');parser.add_argument('--preview',action='store_true');parser.add_argument('--approve-digest');parser.add_argument('--archive')
    args=parser.parse_args();root=args.root.expanduser().resolve(strict=True)
    config=json.loads((root/'control/config.json').read_text())
    stop_owned(root)
    from vault_backup import stopped_runtime,snapshot,restore
    if args.operation=='backup':
        with stopped_runtime(root):print(json.dumps(dict(archive=snapshot(root,config))))
    elif args.operation=='restore':
        archive=args.archive or input('Encrypted backup path (Archive/Backups/…zip): ').strip()
        if not args.archive and input('Restore this snapshot while preserving current data? Type RESTORE: ').strip()!='RESTORE':return
        with stopped_runtime(root):print(json.dumps(dict(previous_webui=str(restore(root,config,archive)),note='Previous Village data is retained separately. Running sessions restore paused; open Local AI explicitly.')))
    else:
        import village
        from village_storage import offline_access,deletion_plan,erase,_read,PENDING
        with stopped_runtime(root):
            pending=_read(root/PENDING,None)
            source=args.source or (pending['source'] if pending else None)
            if not source:
                cx=village.connect(root/'village',maintenance=True)
                try:
                    for r in cx.execute('SELECT sha,filename,state FROM imports'):print(r['sha'],r['filename'],r['state'])
                finally:cx.close()
                source=input('Source SHA to forget: ').strip()
            plan=pending or deletion_plan(root,config,source)
            print(json.dumps(plan,indent=2))
            if args.preview:return
            digest=args.approve_digest
            if digest is None:
                if input('This removes ALL derived Village knowledge, managed working copies/history/logs and managed backups. External copies are not erased. Type FORGET to approve the displayed plan: ').strip()!='FORGET':return
                digest=plan['digest']
            print(json.dumps(erase(root,config,source,digest),indent=2))


if __name__=='__main__':main()
