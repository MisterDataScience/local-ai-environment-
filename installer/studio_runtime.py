"""Portable 320x180 machine. Wasmtime executes only explicit vm imports.

Used in a separate process by studio_workbench. No WASI, filesystem, socket or
process imports are supplied. Every entry has fuel and host drawing is bounded.
"""
import base64
import hashlib
import json
import math
import resource
import struct
import sys
import time
import zlib

WIDTH,HEIGHT=320,180
MAX_MEMORY=16*1024*1024
MAX_SAVE=1024*1024
MAX_INSTANCES=40
FUEL=2_000_000


def png(pixels):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+bytes(pixels[y*WIDTH*4:(y+1)*WIDTH*4]) for y in range(HEIGHT))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',WIDTH,HEIGHT,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')


def global_count(wasm):
    def leb(pos):
        n=0;shift=0
        while True:
            b=wasm[pos];pos+=1;n|=(b&127)<<shift
            if b<128:return n,pos
            shift+=7
            if shift>35:raise ValueError('Invalid Wasm length')
    pos=8
    while pos<len(wasm):
        kind=wasm[pos];length,start=leb(pos+1)
        if kind==6:return leb(start)[0]
        pos=start+length
    return 0


class Machine:
    def __init__(self,engine,wasm,seed=1,assets=None,initial_save=b''):
        import wasmtime as w
        self.w=w;self.engine=engine;self.code=wasm;self.code_hash=hashlib.sha256(wasm).hexdigest()
        self.store=w.Store(engine);self.store.set_limits(memory_size=MAX_MEMORY,table_elements=0,instances=1,tables=0,memories=1)
        self.module=w.Module(engine,wasm);self.seed=seed;self.ticks=0;self.history=[];self.metrics={};self.logs=[]
        self.frame=bytearray(WIDTH*HEIGHT*4);self.save=bytes(initial_save);self.assets=assets or {}
        self.sounds=[];self.draw_ops=0;self.rendering=False
        if len(self.save)>MAX_SAVE or sum(len(v) for v in self.assets.values())>16*1024*1024:raise ValueError('Machine data exceeds budget')
        types={
          'clear':([w.ValType.i32()],[],self.clear),
          'pixel':([w.ValType.i32()]*3,[],self.pixel),
          'rect':([w.ValType.i32()]*5,[],self.rect),
          'tone':([w.ValType.i32()]*4,[],self.tone),
          'metric':([w.ValType.i32()]*2,[],self.metric),
          'save':([w.ValType.i32()]*2,[w.ValType.i32()],self.save_data),
          'load':([w.ValType.i32()]*2,[w.ValType.i32()],self.load_data),
          'asset_size':([w.ValType.i32()],[w.ValType.i32()],self.asset_size),
          'asset_read':([w.ValType.i32()]*4,[w.ValType.i32()],self.asset_read),
        }
        imports=[]
        for imp in self.module.imports:
            if imp.module!='vm' or imp.name not in types or not isinstance(imp.type,w.FuncType):raise PermissionError('Cartridge requests an unsupported capability')
            params,results,fn=types[imp.name]
            imports.append(w.Func(self.store,w.FuncType(params,results),fn,access_caller=imp.name in ('save','load','asset_read')))
        exported_globals=[e for e in self.module.exports if isinstance(e.type,w.GlobalType)]
        if len(exported_globals)!=global_count(wasm):raise ValueError('All globals must be exported for complete save states')
        if any(isinstance(e.type,w.TableType) for e in self.module.exports):raise ValueError('Version one cartridges cannot export mutable function tables')
        self.store.set_fuel(FUEL)
        self.instance=w.Instance(self.store,self.module,imports);self.exports=self.instance.exports(self.store)
        for name in ('vm_init','vm_update','vm_draw','memory'):
            if name not in self.exports:raise ValueError('Cartridge lacks '+name)
        if self.exports['memory'].size(self.store)>MAX_MEMORY//65536:raise ValueError('Cartridge memory exceeds budget')
        self.call('vm_init',seed);self.render()

    def charge(self,amount):
        fuel=self.store.get_fuel()
        if amount>fuel:raise self.w.Trap('Host operation exceeded machine fuel')
        self.store.set_fuel(fuel-amount)

    @staticmethod
    def colour(colour):
        colour&=0xffffff
        return bytes([(colour>>16)&255,(colour>>8)&255,colour&255,255])

    def clear(self,colour):
        self.charge(WIDTH*HEIGHT);self.frame[:]=self.colour(colour)*(WIDTH*HEIGHT)

    def pixel(self,x,y,colour):
        self.charge(8)
        if 0<=x<WIDTH and 0<=y<HEIGHT:self.frame[(y*WIDTH+x)*4:(y*WIDTH+x+1)*4]=self.colour(colour)

    def rect(self,x,y,width,height,colour):
        x0=max(0,min(WIDTH,x));x1=max(x0,min(WIDTH,x+max(0,width)))
        y0=max(0,min(HEIGHT,y));y1=max(y0,min(HEIGHT,y+max(0,height)))
        self.charge(8+(x1-x0)*(y1-y0));row=self.colour(colour)*(x1-x0)
        for line in range(y0,y1):self.frame[(line*WIDTH+x0)*4:(line*WIDTH+x1)*4]=row

    def tone(self,channel,frequency,ticks,volume):
        self.charge(100)
        if not 0<=channel<4 or not 20<=frequency<=20000 or not 0<=ticks<=600 or not 0<=volume<=100:raise ValueError('Invalid tone')
        if len(self.sounds)<64:self.sounds.append(dict(channel=channel,frequency=frequency,ticks=ticks,volume=volume))

    def metric(self,key,value):
        self.charge(20)
        if not 0<=key<128:raise ValueError('Metric key out of range')
        self.metrics[str(key)]=value

    def region(self,caller,pointer,length):
        mem=caller.get('memory')
        if pointer<0 or length<0 or pointer+length>mem.data_len(caller):raise ValueError('Cartridge memory access outside bounds')
        self.charge(20+length)
        return mem

    def save_data(self,caller,pointer,length):
        if self.rendering:raise ValueError('Drawing cannot modify saved data')
        if length>MAX_SAVE:raise ValueError('Saved data exceeds budget')
        mem=self.region(caller,pointer,length);self.save=bytes(mem.read(caller,pointer,pointer+length));return length

    def load_data(self,caller,pointer,length):
        amount=min(max(0,length),len(self.save));mem=self.region(caller,pointer,amount);mem.write(caller,self.save[:amount],pointer);return amount

    def asset_size(self,key):self.charge(10);return len(self.assets.get(str(key),b''))

    def asset_read(self,caller,key,offset,pointer,length):
        data=self.assets.get(str(key),b'')
        if offset<0 or length<0:raise ValueError('Invalid asset read')
        part=data[offset:offset+length];mem=self.region(caller,pointer,len(part));mem.write(caller,part,pointer);return len(part)

    def call(self,name,*args):
        self.store.set_fuel(FUEL);self.exports[name](self.store,*args)

    def state_bytes(self):return bytes(self.exports['memory'].read(self.store))

    def globals(self):
        return {name:value.value(self.store) for name,value in self.exports.items() if isinstance(value,self.w.Global) and value.type(self.store).mutable}

    def render(self):
        before=self.state_bytes();globals_before=self.globals();self.rendering=True
        try:self.call('vm_draw')
        finally:
            self.rendering=False
            # C drawing functions may use stack-local arrays. Restore scratch writes
            # so skipped renders cannot change the simulation or a replay hash.
            self.exports['memory'].write(self.store,before)
            for name,value in globals_before.items():self.exports[name].set_value(self.store,value)
        if len(before)!=self.exports['memory'].data_len(self.store):raise ValueError('Drawing cannot grow memory; allocate during vm_init or vm_update')

    def run(self,steps,buttons=0,stop_metric=None):
        if type(steps) is not int or not 0<=steps<=600 or type(buttons) is not int or not 0<=buttons<=255:raise ValueError('Invalid bounded input batch')
        self.sounds=[];done=0
        for _ in range(steps):
            self.call('vm_update',buttons);self.ticks+=1;done+=1
            if stop_metric and self.metrics.get(str(stop_metric['key']))==stop_metric['value']:break
        if done:
            if self.history and self.history[-1]['buttons']==buttons:self.history[-1]['steps']+=done
            else:self.history.append(dict(steps=done,buttons=buttons))
            if len(self.history)>10000:raise ValueError('Input history quota reached; save and start another experiment')
        self.render();return self.observe()

    def observe(self):
        return dict(ticks=self.ticks,metrics=self.metrics,sounds=self.sounds,png=base64.b64encode(png(self.frame)).decode(),memory_bytes=len(self.state_bytes()),state_sha256=hashlib.sha256(self.state_bytes()).hexdigest(),screen_sha256=hashlib.sha256(self.frame).hexdigest())

    def snapshot(self):
        return dict(version=1,save_format=1,sdk_abi_version=1,code=self.code_hash,seed=self.seed,ticks=self.ticks,memory=base64.b64encode(zlib.compress(self.state_bytes())).decode(),globals=self.globals(),save=base64.b64encode(self.save).decode(),history=self.history,metrics=self.metrics)

    def restore(self,state):
        if state.get('save_format',1)!=1:raise ValueError('Unsupported save format '+str(state.get('save_format')))
        if state.get('sdk_abi_version',1)!=1:raise ValueError('Unsupported SDK ABI '+str(state.get('sdk_abi_version')))
        if state.get('version')!=1 or state.get('code')!=self.code_hash:raise ValueError('Save state belongs to another cartridge')
        decompressor=zlib.decompressobj();raw=decompressor.decompress(base64.b64decode(state['memory'],validate=True),MAX_MEMORY+1)
        if len(raw)>MAX_MEMORY or not decompressor.eof or decompressor.unused_data:raise ValueError('Invalid bounded save state')
        mem=self.exports['memory'];current=mem.data_len(self.store)
        if len(raw)%65536 or len(raw)<current:raise ValueError('Invalid saved memory size')
        if len(raw)>current:mem.grow(self.store,(len(raw)-current)//65536)
        if set(state['globals'])!=set(self.globals()):raise ValueError('Incomplete saved globals')
        mem.write(self.store,raw)
        for name,value in state['globals'].items():self.exports[name].set_value(self.store,value)
        saved=base64.b64decode(state['save'],validate=True)
        if len(saved)>MAX_SAVE:raise ValueError('Save data too large')
        self.save=saved;self.seed=state['seed'];self.ticks=state['ticks'];self.history=state['history'];self.metrics=state['metrics'];self.render()
        return self.observe()


class Runtime:
    def __init__(self):
        import wasmtime as w
        config=w.Config();config.consume_fuel=True;config.wasm_threads=False;config.wasm_memory64=False
        self.engine=w.Engine(config);self.machines={};self.cpu_start=time.process_time();self.wall_start=time.monotonic()

    def execute(self,request):
        operation=request['operation'];mid=request.get('machine','')
        if operation=='create':
            if len(self.machines)>=MAX_INSTANCES:raise ValueError('Host machine limit reached')
            wasm=base64.b64decode(request['wasm'],validate=True)
            if len(wasm)>16*1024*1024:raise ValueError('Cartridge code too large')
            assets={k:base64.b64decode(v,validate=True) for k,v in request.get('assets',{}).items()}
            machine=Machine(self.engine,wasm,request.get('seed',1),assets);self.machines[mid]=machine
            return machine.observe()
        if operation=='drop':self.machines.pop(mid,None);return dict(stopped=True)
        if operation=='status':return dict(instances=len(self.machines),cpu_seconds=time.process_time()-self.cpu_start,wall_seconds=time.monotonic()-self.wall_start)
        if mid not in self.machines:raise ValueError('Machine unavailable; restore its saved state')
        machine=self.machines[mid]
        if operation=='run':return machine.run(request.get('steps',1),request.get('buttons',0),request.get('stop_metric'))
        if operation=='observe':return machine.observe()
        if operation=='snapshot':return machine.snapshot()
        if operation=='restore':return machine.restore(request['state'])
        if operation=='reset':
            self.machines[mid]=Machine(self.engine,machine.code,request.get('seed',machine.seed),machine.assets)
            return self.machines[mid].observe()
        raise ValueError('Unknown machine operation')


def main():
    runtime=Runtime()
    while True:
        line=sys.stdin.buffer.readline(48*1024*1024+1)
        if not line:break
        if len(line)>48*1024*1024:raise ValueError('Runtime request exceeds bound')
        started=time.process_time()
        try:result=dict(ok=True,result=runtime.execute(json.loads(line)))
        except Exception as error:result=dict(ok=False,error=str(error)[:2000])
        result['cpu_ms']=(time.process_time()-started)*1000
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result['peak_rss_bytes']=peak if sys.platform=='darwin' else peak*1024
        print(json.dumps(result,separators=(',',':')),flush=True)
        if result['peak_rss_bytes']>1024*1024*1024:break


if __name__=='__main__':main()
