import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';

test('simulated owner call captures speech, routes to coordinator, plays and scopes approval',async()=>{
  const fixture=new URL('./discord-fixture.mjs',import.meta.url).href;
  const loader=`export async function resolve(s,c,n){if(['discord.js','@discordjs/voice','@snazzah/davey','opusscript'].includes(s))return {url:${JSON.stringify(fixture)},shortCircuit:true};return n(s,c);}`;
  const child=spawn(process.execPath,['--no-warnings','--experimental-loader','data:text/javascript,'+encodeURIComponent(loader),new URL('../discord-adapter.mjs',import.meta.url).pathname],{stdio:['pipe','pipe','pipe']});
  child.stdin.end(JSON.stringify({token:'fixture',bridgeKey:'fixture',config:{owner_id:'111111111111111111',guild_id:'222222222222222222',channel_id:'333333333333333333',bot_id:'444444444444444444'}}));
  let out='',err='';child.stdout.on('data',d=>out+=d);child.stderr.on('data',d=>err+=d);
  const timer=setTimeout(()=>child.kill('SIGKILL'),8000);
  const code=await new Promise(r=>child.on('exit',r));clearTimeout(timer);
  assert.equal(code,0,err+'\n'+out);
  const result=JSON.parse(out.split('RESULT ')[1].trim());
  for(const action of ['start','detect','interrupt','transcribe','submit','played','permission','stop'])assert.ok(result.actions.includes(action),action);
  assert.ok(result.approved&&result.acked&&result.denied);
  assert.equal(result.actions.filter(a=>a==='permission').length,1);
});
