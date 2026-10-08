import test from 'node:test';
import assert from 'node:assert/strict';
import { Endpoint, encodePCM } from '../conversation.mjs';

test('short noise does not commit; sustained speech ends after silence', () => {
  const endpoint=new Endpoint();
  assert.equal(endpoint.update([.9,.9,0,0,0]).start,false);
  assert.equal(endpoint.update([.9,.9,.9]).start,true);
  assert.equal(endpoint.update(Array(8).fill(.9)).valid,true);
  assert.equal(endpoint.update(Array(21).fill(0)).end,false);
  assert.equal(endpoint.update([0]).end,true);
  endpoint.reset(); assert.equal(endpoint.active,false);
});
test('utterances have a hard duration bound', () => {
  const endpoint=new Endpoint();
  assert.equal(endpoint.update(Array(880).fill(.9)).end,true);
});
test('PCM bytes retain signed sample values', () => {
  assert.deepEqual([...Buffer.from(encodePCM([new Int16Array([0,-32768,32767])]),'base64')], [0,0,0,128,255,127]);
});
