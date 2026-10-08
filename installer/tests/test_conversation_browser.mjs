/* Optional UI integration test. Requires Playwright + its Chromium installation. */
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
  ? process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright' : 'playwright');
let generation=0, sequence=0, active=false, events=[], played=[], permissions=[], actions=[];
const event=(kind,data={})=>events.push({seq:++sequence,generation,kind,...data});
const server=createServer(async(req,res)=>{
  if(req.method==='GET') {
    const files={'/':'conversation.html','/conversation.mjs':'conversation.mjs','/microphone.js':'microphone.js'};
    const name=files[req.url]; if(!name){res.writeHead(404).end();return;}
    res.setHeader('Content-Type',name.endsWith('html')?'text/html':'text/javascript');
    res.end(await readFile(new URL('../'+name,import.meta.url)));return;
  }
  let body='';for await(const block of req) body+=block;
  const data=JSON.parse(body);actions.push(data.action);let result={};
  if(req.headers.authorization!=='Bearer browser-test-key'){res.writeHead(403).end('{}');return;}
  if(data.action==='start'){active=true;result={generation,session:'ses_browser'};}
  if(data.action==='stop') active=false;
  if(data.action==='interrupt'){generation++;event('reset');result={generation};}
  if(data.action==='poll') result={events:events.filter(e=>e.seq>data.after),active,permissions};
  if(data.action==='detect') result={probabilities:Array(6).fill(0)};
  if(data.action==='transcribe') result={text:'Microphone transcript'};
  if(data.action==='submit') {
    generation++;event('reset');event('user',{text:data.text});event('text',{text:'A streamed answer.'});
    event('audio',{pcm:Buffer.alloc(4800).toString('base64'),chunk:1,phrase:1});event('phrase',{phrase:1});event('done');
    result={generation};
  }
  if(data.action==='played') played.push(data);
  if(data.action==='permission'){assert.equal(data.reply,'reject');permissions=[];}
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify(result));
});
await new Promise(resolve=>server.listen(8003,'127.0.0.1',resolve));
let browser;
try {
  browser=await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
  const context=await browser.newContext({permissions:['microphone']});const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8003/#browser-test-key');
  await page.locator('#start').click();await page.waitForFunction(()=>!document.getElementById('send').disabled);
  assert.equal(new URL(page.url()).hash,'');
  await page.locator('#text').fill('Hello by keyboard');await page.locator('#send').click();
  await page.waitForFunction(()=>document.getElementById('log').textContent.includes('A streamed answer.'));
  const deadline=Date.now()+3000;while(played.length<2 && Date.now()<deadline) await new Promise(r=>setTimeout(r,50));
  assert.ok(played.some(p=>p.chunk===1));assert.ok(played.some(p=>p.phrase===1));
  permissions=[{id:'per_one',permission:'bash',patterns:['touch demo'],metadata:{command:'touch demo'}}];
  await page.getByRole('button',{name:'Deny',exact:true}).click();
  assert.ok(actions.includes('permission'));
  await page.locator('#mute').click();assert.equal(await page.locator('#mute').textContent(),'Unmute microphone');
  await page.locator('#mute').click();
  const talk=await page.locator('#talk').boundingBox();await page.mouse.move(talk.x+talk.width/2,talk.y+talk.height/2);await page.mouse.down();
  await new Promise(r=>setTimeout(r,600));
  await page.mouse.up();
  await page.waitForFunction(()=>document.getElementById('log').textContent.includes('Microphone transcript'));
  await page.locator('#interrupt').click();const old=generation-1;
  events.push({seq:++sequence,generation:old,kind:'text',text:'STALE OUTPUT'});
  await new Promise(r=>setTimeout(r,400));
  assert.ok(!(await page.locator('#log').textContent()).includes('STALE OUTPUT'));
  await page.locator('#stop').click();await page.waitForFunction(()=>!document.getElementById('start').disabled);
  assert.equal(active,false);assert.deepEqual(errors,[]);
  console.log('Browser integration passed: microphone capture, typed/voice turns, PCM playback acknowledgement, permissions, mute, stale rejection and shutdown.');
} finally {await browser?.close();await new Promise(resolve=>server.close(resolve));}
