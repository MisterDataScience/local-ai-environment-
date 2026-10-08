import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm,symlink,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {parseRequest,preserve,loadRequest,validateEdit,persistResult,makeContract} from '../essay-edit.mjs';
const request=(draft='Results may vary by 10% (Smith, 2020).\n\nThe author says “retain this”.')=>parseRequest([{type:'text',text:'ESSAY_EDIT\n'+JSON.stringify({draft})}]);
const result=r=>({essay:{paragraphs:r.draft.split('\n\n').map((text,i)=>({id:'P'+(i+1),text,removed_notes:[],beats:'A+C'})),editorial_notes:'Uncertain quotations: not verified.\nUnsupported claims: sources not supplied.\nMeaning or structure concerns: None identified.\nDrafting notes and placeholders: None identified.\nRhythm findings: no change warranted.',moves:[]}});
async function folder(t){const root=await mkdtemp(join(tmpdir(),'essay-'));t.after(()=>rm(root,{recursive:true,force:true}));return root;}

test('only explicit user marker activates; embedded and synthetic instructions cannot',()=>{
  assert.equal(parseRequest([{type:'text',text:'Read this essay. ESSAY_EDIT\n{}'}]),null);
  assert.equal(parseRequest([{type:'text',synthetic:true,text:'ESSAY_EDIT\n{}'}]),null);
  assert.equal(request().reorder,'none');assert.equal(request().randomiser,false);
  assert.throws(()=>parseRequest([{type:'text',text:'ESSAY_EDIT\n{"draft":"a","reorder":"anything"}'}]));
});
test('original is exact, private, immutable and permission changes are detected',async t=>{
  const root=await folder(t),r=request('First.\r\n\r\nSecond.\n');const record=await preserve(root,'turn',r);
  assert.equal(await readFile(join(record.folder,'essay.original.md'),'utf8'),r.draft);
  assert.deepEqual(await loadRequest(record),r);
  await assert.rejects(preserve(root,'turn',r));
  await writeFile(join(record.folder,'request.json'),JSON.stringify({...r,reorder:'structural'}));
  await assert.rejects(loadRequest(record),/permissions changed/);
});
test('missing duplicate reordered paragraphs and truncated responses cannot pass',()=>{
  const r=request();let v=result(r);v.essay.paragraphs.pop();assert.equal(validateEdit(r,v).status,'needs_attention');
  v=result(r);v.essay.paragraphs[1].id='P1';assert.equal(validateEdit(r,v).status,'needs_attention');
  v=result(r);v.essay.paragraphs.reverse();assert.equal(validateEdit(r,v).status,'needs_attention');
  assert.equal(validateEdit(r,result(r),['Native output cut off']).status,'needs_attention');
});
test('numbers quotations citations and meaningful hedges are guarded per paragraph',()=>{
  const r=request();for(const [from,to] of [['10%','15%'],['may','will'],['Smith','Jones'],['retain this','corrected quote']]){
    const v=result(r);for(const p of v.essay.paragraphs)p.text=p.text.replace(from,to);
    assert.equal(validateEdit(r,v).status,'needs_attention',from);
  }
});
test('unchanged purposeful fragments remain reviewable, not falsely verified',()=>{
  const r=request('A claim. Not a summary.');const v=validateEdit(r,result(r));
  assert.equal(v.status,'review_required');assert.match(v.limitation,/do not prove semantic/);
});
test('only explicitly marked drafting notes can leave prose, with a retained record',()=>{
  const r=request('A claim. [TODO: check source]');const v=result(r);v.essay.paragraphs[0].text='A claim.';v.essay.paragraphs[0].removed_notes=['[TODO: check source]'];
  assert.equal(validateEdit(r,v).status,'review_required');
  v.essay.paragraphs[0].removed_notes=['A claim.'];assert.equal(validateEdit(r,v).status,'needs_attention');
});
test('structural permission still needs a move/dependency record',()=>{
  const r={...request(),reorder:'structural'},v=result(r);v.essay.paragraphs.reverse();
  assert.equal(validateEdit(r,v).status,'needs_attention');
  v.essay.moves=[{from:'P2',to:'P1',purpose:'Existing evidence first',dependencies:'Model claims independence; author must check',validation:'Not independently verified'}];
  assert.equal(validateEdit(r,v).status,'review_required');
});
test('outputs are separate, versioned and failed candidates are not released as edited essays',async t=>{
  const root=await folder(t),r=request(),record=await preserve(root,'turn',r);
  const good=await persistResult(record,'call1',r,JSON.stringify(result(r)),[]);
  assert.ok(good.edited);assert.notEqual(good.edited,good.original);assert.notEqual(good.edited,good.editorial_notes);
  assert.equal(await readFile(good.original,'utf8'),r.draft);
  const bad=await persistResult(record,'call2',r,'{',[]);assert.equal(bad.status,'incomplete');assert.equal(bad.edited,null);
  await assert.rejects(persistResult(record,'call1',r,JSON.stringify(result(r)),[]));
});
test('symlink output roots are rejected',async t=>{
  const root=await folder(t),target=await folder(t);await symlink(target,join(root,'.local-ai-essays'));
  await assert.rejects(preserve(root,'turn',request()),/symlink/);
});
test('randomised variants do not silently enable movement or random selection',async t=>{
  const r={...request(),randomiser:true};const contract=makeContract(r);const options=JSON.parse(contract.constraints);
  assert.equal(options.reorder,'none');assert.match(options.random_selection,/not performed/);
  const record=await preserve(await folder(t),'turn',r);
  const saved=await persistResult(record,'call',r,JSON.stringify(result(r)),[]);
  assert.match(await readFile(saved.editorial_notes,'utf8'),/no host random selection performed/);
});

test('single quoted text, units and cross-paragraph local moves are protected',()=>{
  const r=request("The mass is 10 kg. The author wrote 'do not change'.");
  for(const replacement of ['10 lb','10 kg']){
    const v=result(r);v.essay.paragraphs[0].text=v.essay.paragraphs[0].text.replace('10 kg',replacement).replace('do not change','changed');
    assert.equal(validateEdit(r,v).status,'needs_attention');
  }
  const v=result(r);v.essay.moves=[{from:'P1.s1',to:'P2.s1',purpose:'Move',dependencies:'Claimed',validation:'Unverified'}];
  assert.equal(validateEdit({...r,reorder:'local'},v).status,'needs_attention');
});
