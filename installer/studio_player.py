"""Export an offline player plus the portable cartridge; no network dependencies."""
import io
import json
import zipfile

PLAYER=r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval'; worker-src blob:; style-src 'unsafe-inline'; img-src data:; connect-src 'none'">
<title>Village cartridge</title><style>body{background:#111820;color:#edf1f5;font:16px system-ui;margin:2rem auto;max-width:1000px;padding:1rem}canvas{display:block;max-width:100%;image-rendering:pixelated;background:#000;margin:1rem 0}button,input{font:inherit;padding:.5rem;margin:.2rem}pre{white-space:pre-wrap}label{display:block}</style>
<h1 id="title">Village cartridge</h1><canvas width="320" height="180" id="screen"></canvas>
<button id="start">Start / resume</button><button id="pause">Pause</button><button id="reset">Reset</button><button id="save">Download save</button>
<label>Restore save <input id="load" type="file" accept="application/json"></label><p>Arrow keys: directions. Z: A. X: B. Enter: Start. Shift: Select. Sound begins after Start.</p><pre id="status">Ready</pre>
<script id="cartridge" type="application/json">__CARTRIDGE__</script>
<script>
const cartridge=JSON.parse(document.getElementById('cartridge').textContent);document.getElementById('title').textContent=cartridge.title;
const canvas=document.getElementById('screen'),ctx=canvas.getContext('2d');let worker,playing=false,pending=false,timer,buttons=0,audio;
function resize(){const scale=Math.max(1,Math.floor(Math.min((innerWidth-48)/320,(innerHeight-280)/180)));canvas.style.width=320*scale+'px';canvas.style.height=180*scale+'px';}addEventListener('resize',resize);resize();
function workerMain(){let instance,mem,frame=new Uint8ClampedArray(320*180*4),saved=new Uint8Array(),assets={},sounds=[],ticks=0,code;
const bytes=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const colour=c=>[(c>>>16)&255,(c>>>8)&255,c&255,255];
const region=(p,n)=>{if(p<0||n<0||p+n>mem.buffer.byteLength)throw Error('Memory bounds');return new Uint8Array(mem.buffer,p,n);};
const imports={vm:{clear(c){const a=colour(c);for(let p=0;p<frame.length;p+=4)frame.set(a,p);},pixel(x,y,c){if(x>=0&&x<320&&y>=0&&y<180)frame.set(colour(c),(y*320+x)*4);},rect(x,y,w,h,c){let a=colour(c);for(let yy=Math.max(0,y);yy<Math.min(180,y+Math.max(0,h));yy++)for(let xx=Math.max(0,x);xx<Math.min(320,x+Math.max(0,w));xx++)frame.set(a,(yy*320+xx)*4);},tone(channel,frequency,ticks,volume){if(sounds.length<64&&channel>=0&&channel<4&&frequency>=20&&frequency<=20000&&ticks>=0&&ticks<=600&&volume>=0&&volume<=100)sounds.push({channel,frequency,ticks,volume});},metric(){},save(p,n){if(n>1048576)throw Error('Save size');saved=region(p,n).slice();return n;},load(p,n){n=Math.min(n,saved.length);region(p,n).set(saved.subarray(0,n));return n;},asset_size(k){return assets[k]?.length||0;},asset_read(k,o,p,n){if(o<0||n<0)throw Error('Asset range');const a=(assets[k]||new Uint8Array()).subarray(o,o+n);region(p,a.length).set(a);return a.length;}}};
function globals(){return Object.fromEntries(Object.entries(instance.exports).filter(([k,v])=>v instanceof WebAssembly.Global).map(([k,v])=>[k,v.value]));}
onmessage=async({data:d})=>{try{if(d.op==='init'){code=d.cartridge;assets=Object.fromEntries(Object.entries(code.assets).map(([k,v])=>[k,bytes(v)]));const result=await WebAssembly.instantiate(bytes(code.wasm),imports);instance=result.instance;mem=instance.exports.memory;instance.exports.vm_init(1);ticks=0;}
if(d.op==='run'){sounds=[];instance.exports.vm_update(d.buttons);ticks++;}
if(d.op==='restore'){if(d.state.source!==code.source_sha256)throw Error('Save belongs to another cartridge');const a=bytes(d.state.memory);if(a.length>16777216||a.length<mem.buffer.byteLength||a.length%65536)throw Error('Save size');if(a.length>mem.buffer.byteLength)mem.grow((a.length-mem.buffer.byteLength)/65536);region(0,a.length).set(a);for(const[k,v]of Object.entries(d.state.globals)){try{instance.exports[k].value=v;}catch{}}saved=bytes(d.state.saved);if(saved.length>1048576||!Number.isSafeInteger(d.state.ticks)||d.state.ticks<0)throw Error('Invalid save');ticks=d.state.ticks;}
if(d.op==='save'){const b64=a=>{let s='';for(let p=0;p<a.length;p+=8192)s+=String.fromCharCode(...a.subarray(p,p+8192));return btoa(s);};postMessage({save:{source:code.source_sha256,memory:b64(new Uint8Array(mem.buffer)),globals:globals(),saved:b64(saved),ticks}});return;}
const before=new Uint8Array(mem.buffer).slice(),beforeGlobals=globals(),beforeSaved=saved;instance.exports.vm_draw();if(mem.buffer.byteLength!==before.length)throw Error('Drawing cannot grow memory');if(saved!==beforeSaved)throw Error('Drawing cannot modify saved data');new Uint8Array(mem.buffer).set(before);for(const[k,v]of Object.entries(beforeGlobals)){try{instance.exports[k].value=v;}catch{}}postMessage({frame:frame.slice(),sounds,ticks});
}catch(e){postMessage({error:String(e)});}};}
function status(s){document.getElementById('status').textContent=s;}
function send(d){if(!worker||pending)return;pending=true;worker.postMessage(d);timer=setTimeout(()=>{worker.terminate();worker=null;playing=false;pending=false;status('Cartridge exceeded the player deadline. Reset to restart.');},2000);}
function boot(){if(worker)worker.terminate();clearTimeout(timer);pending=false;const u=URL.createObjectURL(new Blob(['('+workerMain.toString()+')()'],{type:'text/javascript'}));worker=new Worker(u);URL.revokeObjectURL(u);worker.onmessage=({data:d})=>{clearTimeout(timer);pending=false;if(d.error){playing=false;status(d.error);return;}if(d.save){download(JSON.stringify(d.save),'cartridge-save.json');return;}ctx.putImageData(new ImageData(d.frame,320,180),0,0);status('Simulation step '+d.ticks);if(audio&&playing)for(const s of d.sounds||[]){const o=audio.createOscillator(),g=audio.createGain();o.type='square';o.frequency.value=s.frequency;g.gain.value=s.volume/100*.08;o.connect(g).connect(audio.destination);o.start();o.stop(audio.currentTime+s.ticks/60);}};worker.onerror=e=>{clearTimeout(timer);pending=false;playing=false;status(e.message);};send({op:'init',cartridge});}
function download(text,name){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type:'application/json'}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
document.getElementById('start').onclick=()=>{if(!worker)boot();playing=true;if(!audio)audio=new AudioContext();audio.resume();};document.getElementById('pause').onclick=()=>{playing=false;buttons=0;};document.getElementById('reset').onclick=()=>{playing=false;boot();};document.getElementById('save').onclick=()=>{playing=false;send({op:'save'});};document.getElementById('load').onchange=async e=>{playing=false;try{const f=e.target.files[0];if(f.size>24000000)throw Error('Save too large');send({op:'restore',state:JSON.parse(await f.text())});}catch(e){status(String(e));}};
const keys={ArrowUp:1,ArrowDown:2,ArrowLeft:4,ArrowRight:8,z:16,x:32,Enter:64,Shift:128};addEventListener('keydown',e=>{if(keys[e.key]){buttons|=keys[e.key];e.preventDefault();}});addEventListener('keyup',e=>{buttons&=~(keys[e.key]||0);});addEventListener('blur',()=>{buttons=0;playing=false;});setInterval(()=>{if(playing&&!pending)send({op:'run',buttons});},1000/60);boot();
</script></html>'''


def export(cartridge):
    encoded=json.dumps(cartridge,separators=(',',':')).replace('<','\\u003c')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('player.html',PLAYER.replace('__CARTRIDGE__',encoded))
        z.writestr('cartridge.json',encoded)
        z.writestr('README.txt','Open player.html in a modern browser. No server or model is required.\n320 x 180 pixels; integer scaling. Saved games download locally.\nThis standalone player uses a worker deadline, not the workshop Wasmtime fuel meter.\nBackground testing and owner-session budgets apply inside the studio host.\n')
    return output.getvalue()
