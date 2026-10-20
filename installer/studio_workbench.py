"""Bounded build sandbox and shared Wasm worker; never a resident shell tool."""
import base64
import io
import json
import os
from pathlib import Path
import resource
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

from studio_store import Store,atomic,checked,files,archive,sha,encoded,ident,MAX_PROJECT


def sandbox(command,read_roots,write_root,*,test_trusted=False):
    """Only tests over authored fixtures may bypass unavailable native isolation."""
    if sys.platform!='darwin':
        if test_trusted:return command
        raise RuntimeError('Native build isolation requires macOS sandbox-exec; no unrestricted fallback')
    profile='(version 1)(deny default)(allow process*)(allow sysctl-read)(allow mach-lookup)(allow signal (target self))'
    for path in ['/System','/usr','/bin','/sbin','/Library/Apple','/private/var/db/dyld','/dev/null','/dev/urandom',*map(str,read_roots)]:
        profile+='(allow file-read* (subpath '+json.dumps(str(Path(path).resolve()))+'))'
    profile+='(allow file* (subpath '+json.dumps(str(Path(write_root).resolve()))+'))'
    return ['/usr/bin/sandbox-exec','-p',profile,*map(str,command)]


def limits():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CPU,(120,120))
    resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024*1024,64*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))


class Workbench:
    def __init__(self,store,tool_python=None,zig=None,*,test_trusted=False):
        self.store=store;self.install=store.root.parent;self.control=Path(__file__).parent
        self.tools=self.install/'studio-tools';self.python=Path(tool_python) if tool_python else self.tools/'.venv/bin/python'
        self.zig=Path(zig) if zig else None;self.test_trusted=test_trusted
        self.lock=threading.RLock();self.build_lock=threading.Lock();self.process=None;self.machines={};self.cancel=threading.Event()
        self.credit=200.;self.last=time.monotonic();self.measurements={};self.busy=None
        try:self.measurements=json.loads((store.root/'studio-measurements.json').read_text())
        except (OSError,ValueError):pass

    def status(self):
        return dict(installed=self.python.is_file(),versions=dict(compiler='ziglang 0.14.1',runtime='wasmtime 38.0.0'),instances=[dict(id=k,**v) for k,v in self.machines.items()],measurements=self.measurements,resolution=[320,180],host_cpu_ms_per_second=200,max_instances=40)

    def install_tools(self):
        with self.build_lock:
            self.tools.mkdir(mode=0o700,parents=True,exist_ok=True)
            # Installer already provides a pinned uv; never resolve an arbitrary PATH tool.
            candidates=[self.install/'tools/uv/uv',self.install/'bin/uv',self.install/'uv/uv']
            uv=next((p for p in candidates if p.is_file()),None)
            if uv is None:raise RuntimeError('Pinned installer uv unavailable; rerun the main installer')
            subprocess.run([str(uv),'venv',str(self.tools/'.venv'),'--python',sys.executable],check=True,timeout=120)
            subprocess.run([str(uv),'pip','sync','--python',str(self.python),'--require-hashes','--only-binary',':all:','--no-deps','-r',str(self.control/'locks/studio-tools.txt')],check=True,timeout=900)
            return self.status()

    def compiler(self):
        if self.zig:return self.zig
        if not self.python.exists():raise RuntimeError('Install studio tools from the institution page first')
        out=subprocess.run([str(self.python),'-I','-c','import ziglang,pathlib;print(pathlib.Path(ziglang.__file__).parent/"zig")'],capture_output=True,text=True,check=True,timeout=10)
        return Path(out.stdout.strip())

    def run_process(self,command,work,timeout=120):
        compiler=self.compiler()
        read=[compiler.parent if compiler.name=='zig' else compiler.parent.parent]
        args=sandbox(command,read,work,test_trusted=self.test_trusted)
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(work),'TMPDIR':str(work),'ZIG_GLOBAL_CACHE_DIR':str(work/'.zig-cache'),'ZIG_LOCAL_CACHE_DIR':str(work/'.zig-local')}
        if self.test_trusted and os.environ.get('LD_LIBRARY_PATH'):env['LD_LIBRARY_PATH']=os.environ['LD_LIBRARY_PATH']
        log=work/'.studio-command.log';began=time.monotonic()
        with log.open('wb') as out:
            process=subprocess.Popen(args,cwd=work,env=env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=limits)
            self.busy=process
            try:
                while process.poll() is None:
                    if self.cancel.is_set() or time.monotonic()-began>timeout:raise RuntimeError('Build stopped or exceeded its time budget')
                    if log.stat().st_size>2*1024*1024:raise RuntimeError('Build diagnostic limit exceeded')
                    # Bound output/workspace growth; sandbox also bounds individual files.
                    total=0
                    for p in work.rglob('*'):
                        if p.is_symlink():raise PermissionError('Build created a symbolic link')
                        if p.is_file():total+=p.stat().st_size
                        if total>512*1024*1024:raise RuntimeError('Build storage budget exceeded')
                    time.sleep(.1)
            finally:
                if process.poll() is None:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                process.wait(timeout=10);self.busy=None
        return dict(exit_code=process.returncode,seconds=time.monotonic()-began,diagnostics=log.read_bytes()[-24000:].decode('utf-8','replace'))

    def build(self,pid,kind='cartridge'):
        with self.build_lock:
            if self.cancel.is_set():raise RuntimeError('Workbench is paused')
            entries=files(self.store.path(pid));source_digest=sha(archive(entries));bid=ident('build')
            with self.store.db() as cx:p=self.store.project(cx,pid)
            self.store.quota(p['institution'],len(archive(entries))+sum(len(b) for _,b in entries)+32*1024*1024)
            directory=self.store.directory/p['institution'].split(':')[1]/'builds'/bid.split(':')[1];directory.mkdir(mode=0o700,parents=True)
            work=directory/'work';work.mkdir(mode=0o700)
            for name,data in entries:atomic(checked(work,name),data)
            atomic(directory/'source.zip',archive(entries))
            try:
                if kind=='cartridge':
                    sdk=work/'.studio-sdk';shutil.copytree(self.control/'studio_sdk',sdk)
                    manifest=json.loads(checked(work,'studio.json').read_text())
                    sources=manifest.get('sources')
                    if manifest.get('format')!=1 or not isinstance(sources,list) or not 1<=len(sources)<=1000:raise ValueError('studio.json needs format 1 and C sources')
                    for name in sources:
                        if not name.endswith('.c') or not checked(work,name).is_file():raise ValueError('Unknown C source')
                    out=work/'cartridge.wasm'
                    compiler=self.compiler();prefix=[str(compiler),'cc'] if compiler.name=='zig' else [str(compiler)]
                    target='wasm32-freestanding' if compiler.name=='zig' else 'wasm32-unknown-unknown'
                    command=[*prefix,'-target',target,'-O2','-nostdlib','-fno-builtin','-I',str(sdk),'-I',str(work),*sources,'-Wl,--no-entry','-Wl,--export=vm_init','-Wl,--export=vm_update','-Wl,--export=vm_draw','-Wl,--export=__stack_pointer','-Wl,--export-memory','-Wl,--max-memory=16777216','-Wl,-z,stack-size=65536','-o',str(out)]
                    result=self.run_process(command,work)
                    if result['exit_code']==0:
                        wasm=out.read_bytes()
                        if len(wasm)>16*1024*1024:raise ValueError('Compiled cartridge exceeds 16 MiB host budget')
                        assets={}
                        for key,name in manifest.get('assets',{}).items():
                            if not str(key).isdigit():raise ValueError('Asset IDs must be integers')
                            assets[str(key)]=base64.b64encode(checked(work,name).read_bytes()).decode()
                        if len(wasm)+sum(len(base64.b64decode(v)) for v in assets.values())>16*1024*1024:raise ValueError('Cartridge assets exceed host budget')
                        payload=dict(format=1,title=str(manifest.get('title',p['title']))[:120],width=320,height=180,wasm=base64.b64encode(wasm).decode(),assets=assets,source_sha256=source_digest,tests=manifest.get('tests',[])[:32])
                        atomic(directory/'cartridge.json',encoded(payload).encode())
                elif kind=='reference':
                    # An explicit owner/session allowance authorises the sandboxed build.
                    # Repository makefiles are never run outside the sandbox.
                    if (work/'Makefile').is_file():command=['/usr/bin/make','-j1','CC='+str(self.compiler())+' cc']
                    else:raise ValueError('No Makefile found. Prepare studio.json for the portable target; source remains available for founding.')
                    result=self.run_process(command,work)
                else:raise ValueError('Unknown build kind')
            except Exception as error:result=dict(exit_code=-1,diagnostics=str(error)[:24000])
            state='passed' if result['exit_code']==0 else 'failed'
            with self.store.db() as cx,cx:cx.execute('INSERT INTO studio_builds VALUES(?,?,?,?,?,?,?)',(bid,pid,source_digest,kind,state,encoded(result),int(time.time())))
            atomic(directory/'report.json',encoded(result).encode())
            # Keep source.zip, cartridge and report; compiler caches are disposable.
            shutil.rmtree(work)
            if state=='passed' and kind=='cartridge' and not self.measurements.get('calibration'):
                try:self.calibrate(bid)
                except Exception as error:self.measurements['calibration_error']=str(error)[:1000]
            return dict(id=bid,state=state,source_sha256=source_digest,**result)

    def calibrate(self,bid):
        """Measure the first real cartridge automatically; never estimate the owner's Mac."""
        cartridge,_=self.cartridge(bid);created=[];samples=[]
        with self.lock:
            try:
                for n in range(min(10,40-len(self.machines))):
                    mid='calibration-'+str(n);started=time.monotonic()
                    self.rpc(dict(operation='create',machine=mid,wasm=cartridge['wasm'],assets=cartridge['assets'],seed=1));created.append(mid)
                    cpu=0
                    for _ in range(15):
                        result=self.rpc(dict(operation='run',machine=mid,steps=4,buttons=0));cpu+=self.measurements['last_cpu_ms']
                    samples.append(dict(instances=n+1,steps=60,cpu_ms=cpu,wall_seconds=time.monotonic()-started,guest_memory_bytes=result['memory_bytes']))
                self.measurements['calibration']=dict(build=bid,samples=samples,note='Measured on this host and cartridge. Inference, builds and other programs consume additional resources.')
                atomic(self.store.root/'studio-measurements.json',encoded(self.measurements).encode())
            finally:
                for mid in created:
                    if not self.cancel.is_set():self.rpc(dict(operation='drop',machine=mid))

    def cartridge(self,bid,iid=None):
        with self.store.db() as cx:
            row=cx.execute("SELECT b.*,p.institution FROM studio_builds b JOIN studio_projects p ON p.id=b.project WHERE b.id=? AND b.state='passed' AND b.kind='cartridge' AND p.state='active'",(bid,)).fetchone()
            if not row or iid and row['institution']!=iid:raise PermissionError('Cartridge unavailable')
        path=self.store.directory/row['institution'].split(':')[1]/'builds'/bid.split(':')[1]/'cartridge.json'
        return json.loads(path.read_text()),dict(row)

    def start_worker(self):
        if self.process and self.process.poll() is None:return
        if not self.python.exists():raise RuntimeError('Install studio tools first')
        self.process=subprocess.Popen([str(self.python),str(self.control/'studio_runtime.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True,env={'PATH':'/usr/bin:/bin','PYTHONPATH':os.environ.get('PYTHONPATH','') if self.test_trusted else ''})
        self.machines={}

    def rpc(self,request):
        with self.lock:
            if self.cancel.is_set():raise RuntimeError('Workbench is paused')
            self.start_worker()
            # Global token bucket counts actual worker CPU, including render and Wasm compilation.
            now=time.monotonic();self.credit=min(200,self.credit+(now-self.last)*200);self.last=now
            while self.credit<0:
                if self.cancel.wait(min(.1,-self.credit/200)):raise RuntimeError('Workbench paused')
                now=time.monotonic();self.credit=min(200,self.credit+(now-self.last)*200);self.last=now
            self.process.stdin.write((encoded(request)+'\n').encode());self.process.stdin.flush()
            selector=selectors.DefaultSelector();selector.register(self.process.stdout,selectors.EVENT_READ)
            deadline=time.monotonic()+20
            try:
                while not selector.select(.1):
                    if self.cancel.is_set() or time.monotonic()>deadline:
                        self.kill_worker();raise RuntimeError('Machine stopped or exceeded host deadline')
                raw=self.process.stdout.readline(48*1024*1024)
                if not raw:raise RuntimeError('Machine worker exited; saved state remains available')
                result=json.loads(raw)
            finally:selector.close()
            self.credit-=result.get('cpu_ms',0);self.measurements['last_cpu_ms']=result.get('cpu_ms',0)
            self.measurements['peak_worker_rss_bytes']=result.get('peak_rss_bytes',0)
            if result.get('peak_rss_bytes',0)>1024*1024*1024:
                self.kill_worker();raise RuntimeError('Worker exceeded its 1 GiB resident-memory threshold; restore a saved experiment with fewer instances')
            if not result['ok']:raise RuntimeError(result['error'])
            return result['result']

    def create(self,iid,bid,seed=1):
        with self.lock:
            if sum(v['institution']==iid for v in self.machines.values())>=10:raise ValueError('Ten instances per institution maximum')
            if len(self.machines)>=40:raise ValueError('Forty instances per host maximum')
            cartridge,row=self.cartridge(bid,iid);mid=ident('machine')
            result=self.rpc(dict(operation='create',machine=mid,wasm=cartridge['wasm'],assets=cartridge['assets'],seed=seed))
            self.machines[mid]=dict(institution=iid,build=bid,project=row['project'])
            return dict(machine=mid,**result)

    def machine(self,iid,mid,operation,**args):
        with self.lock:
            if mid not in self.machines or self.machines[mid]['institution']!=iid:raise PermissionError('Machine belongs to another institution or is not running')
            with self.store.db() as cx:self.store.project(cx,self.machines[mid]['project'],iid)
            if operation=='run':
                steps=args.get('steps',1)
                if type(steps) is not int or not 0<=steps<=600:raise ValueError('A batch is 0 to 600 steps')
                result=self.rpc(dict(operation='observe',machine=mid))
                for offset in range(0,steps,4):
                    result=self.rpc(dict(operation='run',machine=mid,**dict(args,steps=min(4,steps-offset))))
                    stop=args.get('stop_metric')
                    if stop and result['metrics'].get(str(stop['key']))==stop['value']:break
            else:result=self.rpc(dict(operation=operation,machine=mid,**args))
            if operation=='snapshot':
                self.store.quota(iid,len(encoded(result)))
                saved=ident('machine');target=self.store.directory/iid.split(':')[1]/'machines'/(saved.split(':')[1]+'.json')
                atomic(target,encoded(dict(meta=self.machines[mid],state=result)).encode());return dict(saved=saved)
            if operation=='drop':self.machines.pop(mid,None)
            if operation in ('run','reset','restore'):
                state=self.rpc(dict(operation='snapshot',machine=mid))
                atomic(self.store.directory/iid.split(':')[1]/'machines'/(mid.split(':')[1]+'.json'),encoded(dict(meta=self.machines[mid],state=state)).encode())
            return result

    def restore(self,iid,saved):
        if not isinstance(saved,str) or not saved.startswith('machine:') or len(saved)!=40:raise ValueError('Invalid saved machine')
        path=self.store.directory/iid.split(':')[1]/'machines'/(saved.split(':')[1]+'.json')
        content=json.loads(path.read_text());result=self.create(iid,content['meta']['build'],content['state']['seed'])
        restored=self.machine(iid,result['machine'],'restore',state=content['state']);return dict(machine=result['machine'],**restored)

    def tests(self,iid,bid):
        cartridge,_=self.cartridge(bid,iid);results=[]
        for test in cartridge['tests']:
            instance=self.create(iid,bid,test.get('seed',1));mid=instance['machine'];observation=instance
            try:
                inputs=test.get('inputs',[])
                if len(inputs)>100:raise ValueError('Test input limit exceeded')
                for action in inputs:observation=self.machine(iid,mid,'run',steps=action['steps'],buttons=action.get('buttons',0))
                passed=all(observation['metrics'].get(str(k))==v for k,v in test.get('expect_metrics',{}).items())
                results.append(dict(name=test.get('name','test'),passed=passed,metrics=observation['metrics'],state_sha256=observation['state_sha256']))
            finally:self.machine(iid,mid,'drop')
        return dict(tests=results,passed=bool(results) and all(r['passed'] for r in results),note='Behavioural assertions; visual quality is not established by these checks')

    def kill_worker(self):
        if self.process:
            if self.process.poll() is None:
                try:os.killpg(self.process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            self.process.wait(timeout=10)
            for p in (self.process.stdin,self.process.stdout):
                if p:p.close()
        self.process=None;self.machines={}

    def pause(self):
        self.cancel.set()
        if self.busy and self.busy.poll() is None:
            try:os.killpg(self.busy.pid,signal.SIGKILL)
            except ProcessLookupError:pass

    def resume(self):self.cancel.clear()

    def shutdown(self):
        self.pause()
        with self.lock:self.kill_worker()
