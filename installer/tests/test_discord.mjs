import test from 'node:test';
import assert from 'node:assert/strict';
import {permitted,pcmToDiscord,Downsample,PlaybackLedger,Capture,permissionDetails,isPrivateChannel} from '../discord-core.mjs';

test('only bound owner in bound guild and channel can operate controls',()=>{
  const c={owner_id:'a',guild_id:'b',channel_id:'c'};
  assert.ok(permitted(c,'a','b','c'));
  for(const args of [['x','b','c'],['a','x','c'],['a','b','x']])assert.equal(permitted(c,...args),false);
});
test('24 kHz mono becomes signed stereo 48 kHz without changing duration',()=>{
  const pcm=Buffer.alloc(4);pcm.writeInt16LE(-32768,0);pcm.writeInt16LE(32767,2);
  const out=pcmToDiscord(pcm);
  assert.deepEqual(Array.from({length:8},(_,i)=>out.readInt16LE(i*2)),[-32768,-32768,-32768,-32768,32767,32767,32767,32767]);
  assert.throws(()=>pcmToDiscord(Buffer.alloc(1)));assert.throws(()=>pcmToDiscord(Buffer.alloc(24002)));
});
test('48 kHz stereo downsampling carries split frames',()=>{
  const source=Buffer.alloc(24);for(let i=0;i<12;i++)source.writeInt16LE(i<6?-1200:2400,i*2);
  const d=new Downsample(),parts=[d.push(source.subarray(0,5)),d.push(source.subarray(5,17)),d.push(source.subarray(17))];
  const out=Buffer.concat(parts);assert.equal(out.length,4);assert.equal(out.readInt16LE(0),-1200);assert.equal(out.readInt16LE(2),2400);
});
test('acknowledge only elapsed playback; incomplete phrases remain unacknowledged',()=>{
  const l=new PlaybackLedger(7);l.chunk(1,24000);l.chunk(2,24000);l.phrase(3);
  assert.deepEqual(l.advance(499),[]);assert.deepEqual(l.advance(500),[{generation:7,chunk:1}]);
  assert.deepEqual(l.advance(999),[]);assert.deepEqual(l.advance(1000),[{generation:7,chunk:2},{generation:7,phrase:3}]);
  assert.deepEqual(l.advance(2000),[]);
});
test('speech capture rejects noise and caps retained PCM',()=>{
  const c=new Capture();assert.equal(c.detect([.9,.9,0]),false);assert.equal(c.detect([.8,.8,.8]),true);
  c.push(Buffer.alloc(896000));assert.throws(()=>c.push(Buffer.alloc(2)));
});
test('permission review retains full arguments and disables oversized approval',()=>{
  const p={permission:'bash',patterns:['rm'],metadata:{command:'long exact command'}};
  assert.deepEqual(JSON.parse(permissionDetails(p).full),p);
  assert.equal(permissionDetails({...p,metadata:{command:'a'.repeat(100001)}}).allow,false);
});
test('private channel rejects broad grants and non-owner servers',()=>{
  const c={guild_id:'g',owner_id:'o',bot_id:'b'};
  const rule=(id,allow,deny)=>({id,allow:{has:()=>allow},deny:{has:()=>deny}});
  const channel={guild:{ownerId:'o'},permissionOverwrites:{cache:new Map([['g',rule('g',false,true)],['o',rule('o',true,false)]])}};
  assert.ok(isPrivateChannel(channel,c));channel.permissionOverwrites.cache.set('role',rule('role',true,false));assert.equal(isPrivateChannel(channel,c),false);
  channel.permissionOverwrites.cache.delete('role');channel.guild.ownerId='x';assert.equal(isPrivateChannel(channel,c),false);
});
