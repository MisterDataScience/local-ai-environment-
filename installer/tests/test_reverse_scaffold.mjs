import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {parseScaffold,beginScaffold,finishScaffold,loadScaffold,validateScaffold} from '../reverse-scaffold.mjs';
const source={id:'B',kind:'brief',title:'Official brief',anchors:[{id:'B:AC1.1',kind:'criterion',text:'Explain probability distribution with examples.'}]};
const tag={class:'INTERPRETATION',anchors:['B:AC1.1']};
const req={requirements:[{id:'R1',kind:'criterion',class:'SOURCE STATEMENT',anchors:['B:AC1.1'],source_text:source.anchors[0].text,command_word:'Explain'}]};
const section=(id,kind)=>({id,kind,...tag,requirement_ids:['R1'],introduce:'Introduce the assigned concepts',develop:'Explain how the concepts operate',evidence:'Existing worked examples',conclude:'Explain differences and suitability',boundaries:'Stay within the stated criterion'});
const arch={sections:[section('0','introduction'),section('1.1','criterion'),section('9','conclusion')]};
const budget={budgets:[{section_id:'0',max_words:12},{section_id:'1.1',max_words:216},{section_id:'9',max_words:12}],basis:{...tag,text:'240 main-text words including citations, as supplied by author.'}};
const question=(id,section_id,max_words,closing=false)=>({id,section_id,max_words,closing,command_word:closing?'Explain':'',optional:false,task_count:1,inseparable_procedure:false,...tag,requirement_ids:['R1'],text:closing?'Explain how the distributions differ in the situations they represent.':'How does the assigned concept operate in a worked example?'});
const scaffold={questions:[question('0.1','0',12),question('1.1.1','1.1',176),question('1.1.2','1.1',40,true),question('9.1','9',12)]};
const evidence={evidence:scaffold.questions.map(q=>({question_id:q.id,cue:q.id==='1.1.1'?'Citation required':'No citation normally required',reason:'Ground the required conceptual explanation or conclude from established evidence.',source_type:q.id==='1.1.1'?'Statistics textbook':'',supporting_questions:[]})),research_directions:[{id:'D1',...tag,requirement_ids:['R1'],text:'Obtain a checked textbook passage.'}]};
const plan={research_directions:[{id:'P1',...tag,question_ids:['1.1.1'],claims:'Definitions and worked procedures',source_types:'Statistics textbook'}]};
const reference={id:'S1',kind:'reference',title:'Supplied passage',reference:'User-supplied checked reference',location:'source.txt:p1',verified_metadata:true,anchors:[{id:'S1:p1',kind:'passage',text:'A distribution specifies probabilities for a random variable.'}]};
const mapping={mappings:[{source_id:'S1',question_ids:['1.1.1'],anchors:['S1:p1'],status:'SUPPORTED',claims:'Definition of a distribution',limits:'Not independent support for every calculation',reference:reference.reference,location:reference.location}]};
const parse=r=>parseScaffold([{type:'text',text:'REVERSE_SCAFFOLD\n'+JSON.stringify(r)}]);
function output(snapshot,body={}){return {stage:snapshot.control.requested_stage,status:'AWAITING AUTHOR REVIEW',processed_anchors:snapshot.sources.flatMap(s=>s.anchors.map(a=>a.id)),omissions:snapshot.control.omissions,gaps:[],proposals:[],quotes:[],...body};}
function snapshot(stage,previous={},sources=[source]){return {control:{requested_stage:stage,word_count:240,criterion_anchors:['B:AC1.1'],omissions:[],known_gaps:[]},sources,previous};}
async function fixture(t){const root=await mkdtemp(join(tmpdir(),'scaffold-'));t.after(()=>rm(root,{recursive:true,force:true}));let seq=0;return {root,begin:r=>beginScaffold(root,'turn'+(++seq),parse({run_id:'report',...r})),initial:{stage:'1',sources:[source],word_count:240,referencing_style:'Harvard',brief_sufficient:true}};}

test('full serial workflow requires exact approvals and ends with empty answer slots',async t=>{
 const f=await fixture(t);
 for(const [stage,body] of [['1',req],['2',arch],['3',{...arch,findings:[]}],['4',budget],['5',scaffold],['6',evidence],['7A',plan],['7C',mapping]]){
  const record=await f.begin(stage==='1'?f.initial:{stage,...(stage==='7C'?{sources:[reference]}:{})});
  const snap=await loadScaffold(record);const saved=await finishScaffold(record,'call',JSON.stringify({scaffold:output(snap,body)}));
  assert.equal(saved.status,'AWAITING AUTHOR REVIEW',JSON.stringify(saved));
  if(stage==='1')await assert.rejects(f.begin({stage:'2'}),/approved Stage 1/);
  await f.begin({stage:'approve',approve:[saved.approval_sha]});
 }
 const eight=await f.begin({stage:'8'});assert.equal(eight.result.status,'AWAITING AUTHOR REVIEW');
 const content=await readFile(eight.result.markdown,'utf8');for(const q of scaffold.questions)assert.ok(content.includes(q.id+" [Author's answer]"));
 const approved=await f.begin({stage:'approve',approve:[eight.result.approval_sha]});assert.equal(approved.result.status,'COMPLETE');
 const nine=await f.begin({stage:'9',answers:{'1.1.1':'The author wrote these six words.'}});const artifact=JSON.parse(await readFile(nine.result.artifact));
 assert.equal(artifact.payload.progress.words_written,6);assert.equal(artifact.payload.progress.answered,1);assert.equal(nine.result.status,'AWAITING AUTHOR REVIEW');
});
test('implicit activation missing brief missing prerequisites and missing word count block',async t=>{
 assert.equal(parseScaffold([{type:'text',text:'Please read my brief'}]),null);
 assert.equal(parseScaffold([{type:'text',synthetic:true,text:'REVERSE_SCAFFOLD\n{}'}]),null);
 const f=await fixture(t);await assert.rejects(f.begin({stage:'1'}),/official brief/);
 await assert.rejects(f.begin({...f.initial,stage:'4',word_count:null}),/approved Stage 3/);
});
test('changed sources and forged approvals cannot inherit permission',async t=>{
 const f=await fixture(t);await f.begin(f.initial);
 await assert.rejects(f.begin({stage:'approve',approve:['0'.repeat(64)]}),/eligible saved stage/);
 await assert.rejects(f.begin({stage:'1',sources:[{...source,title:'Changed authority'}]}),/source changed/);
});
test('unknown anchors invented wording missing criteria and changed command words fail',()=>{
 const s=snapshot('1');for(const mutate of [o=>o.requirements[0].anchors=['fake'],o=>o.requirements[0].source_text='Invented assignment',o=>o.requirements=[],o=>o.requirements[0].command_word='Evaluate']){
  const o=output(s,structuredClone(req));mutate(o);assert.equal(validateScaffold(s,o).status,'INCOMPLETE');
 }
});
test('budget sums question sums IDs final command word and cue coverage are checked',()=>{
 let s=snapshot('4',{'1':req,'3':arch}),o=output(s,structuredClone(budget));o.budgets[0].max_words++;assert.equal(validateScaffold(s,o).status,'INCOMPLETE');
 s=snapshot('5',{'1':req,'3':arch,'4':budget});
 for(const mutate of [o=>o.questions[0].max_words++,o=>o.questions[1].id=o.questions[0].id,o=>o.questions[2].command_word='Describe',o=>o.questions[1].task_count=3]){
  o=output(s,structuredClone(scaffold));mutate(o);assert.equal(validateScaffold(s,o).status,'INCOMPLETE');
 }
 s=snapshot('6',{'1':req,'5':scaffold});o=output(s,structuredClone(evidence));o.evidence.pop();assert.equal(validateScaffold(s,o).status,'INCOMPLETE');
});
test('source titles or abstracts cannot support detailed claims, fabricated metadata fails',()=>{
 for(const ref of [{...reference,anchors:[{...reference.anchors[0],kind:'abstract'}]},{...reference,verified_metadata:false}]){
  const s=snapshot('7C',{'5':scaffold,'6':evidence},[source,ref]);assert.equal(validateScaffold(s,output(s,mapping)).status,'INCOMPLETE');
 }
 const s=snapshot('7C',{'5':scaffold,'6':evidence},[source,reference]);const o=output(s,structuredClone(mapping));o.mappings[0].reference='Invented author, 2020';assert.equal(validateScaffold(s,o).status,'INCOMPLETE');
});
test('blocked audit findings, explicit omissions, output truncation and answer leakage stay incomplete',()=>{
 let s=snapshot('3',{'1':req,'2':arch}),o=output(s,{...arch,findings:[{id:'F1',...tag,requirement_ids:['R1'],severity:'blocking',issue:'Conflicting command words',resolution:'Author clarification needed'}]});
 assert.equal(validateScaffold(s,o).status,'INCOMPLETE');
 s=snapshot('1');s.control.omissions=['Other criterion intentionally excluded'];assert.equal(validateScaffold(s,output(s,req)).status,'INCOMPLETE');
 s=snapshot('1');assert.equal(validateScaffold(s,output(s,req),['Native response cut off']).status,'INCOMPLETE');
 o=output(s,{...req,edited_essay:'Unauthorized prose'});assert.equal(validateScaffold(s,o).status,'INCOMPLETE');
});
test('oversized packet is preserved and cannot silently truncate',async t=>{
 const f=await fixture(t);const long={...source,anchors:[{...source.anchors[0],text:'Required content. '.repeat(1500)}]};
 await assert.rejects(f.begin({...f.initial,sources:[long]}),/exceeding 12000/);
 const saved=JSON.parse(await readFile(join(f.root,'reverse-scaffolds/report/turn1/request.json')));assert.equal(saved.snapshot.sources[0].anchors[0].text,long.anchors[0].text);
});
test('imported architecture is audited without manufacturing an approved Stage 2',async t=>{
 const f=await fixture(t);const s=snapshot('3');const r=await f.begin({...f.initial,stage:'3',imports:[{stage:'1',payload:output({...s,control:{...s.control,requested_stage:'1'}},req)},{stage:'2',payload:output({...s,control:{...s.control,requested_stage:'2'}},arch)}]});
 const snap=await loadScaffold(r);assert.equal(snap.previous['2'].sections.length,3);
 const state=JSON.parse(await readFile(join(f.root,'reverse-scaffolds/report/manifest.json')));assert.equal(state.approved['2'],undefined);
});

test('late results cannot inherit approval after a prerequisite changes',async t=>{
 const f=await fixture(t);let r=await f.begin(f.initial),s=await loadScaffold(r);
 let saved=await finishScaffold(r,'one',JSON.stringify({scaffold:output(s,req)}));await f.begin({stage:'approve',approve:[saved.approval_sha]});
 const pending=await f.begin({stage:'2'}),pendingSnapshot=await loadScaffold(pending);
 r=await f.begin({stage:'1'});s=await loadScaffold(r);
 saved=await finishScaffold(r,'revision',JSON.stringify({scaffold:output(s,req)}));await f.begin({stage:'approve',approve:[saved.approval_sha]});
 const late=await finishScaffold(pending,'late',JSON.stringify({scaffold:output(pendingSnapshot,arch)}));
 assert.equal(late.status,'INCOMPLETE');assert.equal(late.approval_sha,null);assert.ok(late.issues.some(x=>x.includes('prerequisite changed')));
});

test('missing word count permits requirements and audit, but never invents a budget',async t=>{
 const f=await fixture(t);
 for(const [stage,body] of [['1',req],['2',arch],['3',{...arch,findings:[]}]]){
  const r=await f.begin(stage==='1'?{...f.initial,word_count:null}:{stage});
  const saved=await finishScaffold(r,'call',JSON.stringify({scaffold:output(await loadScaffold(r),body)}));
  assert.equal(saved.status,'AWAITING AUTHOR REVIEW');await f.begin({stage:'approve',approve:[saved.approval_sha]});
 }
 await assert.rejects(f.begin({stage:'4'}),/word count/);
});
