import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

test('studio owner page and exported player scripts parse',async()=>{
  for(const relative of ['../payload/institutions.html','../studio_player.py']){
    const source=await readFile(new URL(relative,import.meta.url),'utf8');
    for(const match of source.matchAll(/<script>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
  }
});

test('standalone worker executes real C Wasm and restores pixels and state',
 {skip:!process.env.STUDIO_TEST_WASM},async()=>{
  const source=await readFile(new URL('../studio_player.py',import.meta.url),'utf8');
  const worker=source.slice(source.indexOf('function workerMain()'),source.indexOf('function status(s)'));
  let result;
  const context={WebAssembly,Uint8ClampedArray,Uint8Array,atob,btoa,postMessage:value=>result=value};
  vm.createContext(context);vm.runInContext(worker+'workerMain();',context);
  const cartridge={wasm:(await readFile(process.env.STUDIO_TEST_WASM)).toString('base64'),assets:{},source_sha256:'fixture'};
  const send=async data=>{await context.onmessage({data});assert(!result.error,result.error);};
  await send({op:'init',cartridge});
  for(let n=0;n<10;n++)await send({op:'run',buttons:8});
  assert.equal(result.ticks,10);assert.equal(result.frame.length,320*180*4);
  assert.deepEqual(Array.from(result.frame.slice((80*320+27)*4,(80*320+27)*4+4)),[255,203,114,255]);
  const frame=Array.from(result.frame);
  await send({op:'save'});const saved=result.save;
  await send({op:'run',buttons:2});await send({op:'restore',state:saved});
  assert.equal(result.ticks,10);assert.deepEqual(Array.from(result.frame),frame);
 });
