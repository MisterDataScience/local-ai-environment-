// Stage state and deterministic validators. No inference, tools or source acquisition.
import {mkdir,lstat,readFile,open,rename} from 'node:fs/promises';
import {join} from 'node:path';
import {hash,RESULT_INSTRUCTION,bindContract} from './handoff-contract.mjs';
import {writeNew} from './essay-edit.mjs';
export const PREFIX='REVERSE_SCAFFOLD\n';
const fail=s=>{throw Error('Reverse scaffold: '+s);};
const stages=['1','2','3','4','5','6','7A','7C','8','9'];
const classes=['SOURCE STATEMENT','INTERPRETATION','PROPOSED ADDITION','UNRESOLVED GAP'];
const cues=['Citation required','Evidence already cited in section','No citation normally required','UNRESOLVED GAP'];
const idOK=s=>typeof s==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/.test(s);
const list=x=>Array.isArray(x)?x:[];
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const unique=a=>new Set(a).size===a.length;
const setSame=(a,b)=>unique(a)&&unique(b)&&a.length===b.length&&a.every(x=>b.includes(x));
const text=x=>typeof x==='string'&&x.trim().length>0;
const count=s=>(s.match(/\S+/gu)||[]).length;
const schemas={
 '1':'requirements:[{id,kind:criterion|outcome|rule|mandatory|exclusion,class,anchors:[exact anchor IDs],source_text:exact source wording,command_word:string}]. Include separate INTERPRETATION rows for command-word depth; do not replace assessed source wording.',
 '2':'sections:[{id:numeric section ID e.g. 1.1,kind:introduction|criterion|conclusion,class,anchors,requirement_ids,introduce,develop,evidence,conclude,boundaries}]. Each criterion gets a main section; include report introduction and conclusion.',
 '3':'findings:[{id,class,anchors,requirement_ids,severity:blocking|advisory,issue,resolution}], sections:[same complete section schema as Stage 2]. Corrections remain proposals.',
 '4':'budgets:[{section_id,max_words:positive integer}], basis:{class,anchors,text:brief-specific inclusion/exclusion rules}. Sum exactly to CONTROL word_count.',
 '5':'questions:[{id:nested numeric ID e.g. 1.1.1,section_id,requirement_ids,class,anchors,text,max_words:positive integer,closing:boolean,command_word:string,optional:boolean,task_count:1,inseparable_procedure:false}]. IDs start with section_id plus dot. Question maxima sum exactly to approved section budgets. Last question of each criterion is closing and copies its command word.',
 '6':'evidence:[{question_id,cue:Citation required|Evidence already cited in section|No citation normally required|UNRESOLVED GAP,reason,source_type,supporting_questions:[]}], research_directions:[{id,class,anchors,requirement_ids,text}]. Exactly one cue per existing question. No actual references.',
 '7A':'research_directions:[{id,class,anchors,question_ids,claims,source_types}]. Plan source acquisition only, do not claim to have searched or read anything absent from SOURCE.',
 '7C':'mappings:[{source_id,question_ids,anchors,status:SUPPORTED|UNVERIFIED,claims,limits,reference:exact supplied reference or empty,location:exact supplied location or empty}]. SUPPORTED needs a supplied passage anchor and verified metadata. A title or abstract is insufficient; unresolved mappings are UNVERIFIED.',
};
export function parseScaffold(parts){
 const raw=parts.filter(p=>p.type==='text'&&!p.synthetic).map(p=>p.text).join('\n');if(!raw.startsWith(PREFIX))return null;
 let r;try{r=JSON.parse(raw.slice(PREFIX.length));}catch{fail('request must be JSON');}
 if(!r||Array.isArray(r)||Object.keys(r).some(k=>!['run_id','stage','sources','word_count','referencing_style','brief_sufficient','depends_on_spec','criterion_anchors','omissions','approve','imports','answers'].includes(k)))fail('unknown request field');
 if(!/^[a-z][a-z0-9_-]{0,39}$/.test(r.run_id))fail('invalid run ID');
 r.stage=String(r.stage);if(![...stages,'approve'].includes(r.stage))fail('stage must be 1–6, 7A, 7C, 8 or 9');
 for(const k of ['sources','criterion_anchors','omissions','approve','imports']){r[k]??=[];if(!Array.isArray(r[k]))fail(k+' must be a list');}
 if(r.omissions.some(x=>!text(x))||r.approve.some(x=>!/^([a-f0-9]{64})$/.test(x)))fail('invalid omissions or approval hash');
 if(r.word_count!==undefined&&r.word_count!==null&&(!Number.isSafeInteger(r.word_count)||r.word_count<=0))fail('word_count must be a positive integer or null');
 if(r.referencing_style!==undefined&&r.referencing_style!==null&&typeof r.referencing_style!=='string')fail('referencing_style must be text or null');
 for(const k of ['brief_sufficient','depends_on_spec'])if(r[k]!==undefined&&typeof r[k]!=='boolean')fail(k+' must be boolean');
 if(r.stage==='9'&&(!r.answers||typeof r.answers!=='object'||Array.isArray(r.answers)))fail('Stage 9 requires author-written answers keyed by question ID');
 if(r.stage!=='9'&&r.answers!==undefined)fail('answers are only accepted by the Stage 9 counter');
 return r;
}
export function validateSources(sources){
 if(sources.length>40||!unique(sources.map(s=>s?.id)))fail('source IDs must be unique; at most 40 sources');
 const anchors=[];
 for(const s of sources){
  if(!s||!idOK(s.id)||!['brief','spec','rules','reference','context'].includes(s.kind)||!text(s.title)||!Array.isArray(s.anchors))fail('invalid source manifest');
  if(Object.keys(s).some(k=>!['id','kind','title','anchors','reference','location','verified_metadata'].includes(k)))fail('unknown source field');
  if(s.verified_metadata!==undefined&&typeof s.verified_metadata!=='boolean')fail('verified_metadata must be boolean');
  for(const field of ['reference','location'])if(s[field]!==undefined&&typeof s[field]!=='string')fail('invalid source metadata');
  for(const a of s.anchors){if(!a||!idOK(a.id)||!a.id.startsWith(s.id+':')||!text(a.text)||!['criterion','outcome','rule','passage','abstract','title','context'].includes(a.kind))fail('invalid host-supplied anchor');anchors.push(a.id);}
 }
 if(!unique(anchors))fail('duplicate anchors');
 return new Map(sources.flatMap(s=>s.anchors.map(a=>[a.id,{...a,source:s.id,source_kind:s.kind}])));
}
async function folder(path){await mkdir(path,{recursive:true,mode:0o700});if((await lstat(path)).isSymbolicLink())fail('state directory must not be a symlink');}
async function save(path,value){const tmp=path+'.tmp';const f=await open(tmp,'w',0o600);try{await f.writeFile(JSON.stringify(value,null,2)+'\n');await f.sync();}finally{await f.close();}await rename(tmp,path);}
async function readState(base,run){const path=join(base,'reverse-scaffolds',run,'manifest.json');return JSON.parse(await readFile(path,'utf8'));}
function need(state,stage){const x=state.approved[stage];if(!x)fail('approved Stage '+stage+' is required');return x.payload;}
function payload(state,stage){return state.approved[stage]?.payload;}
function requirements(state){return payload(state,'1')?.requirements||state.imports?.['1']?.requirements||[];}
function sections(state){return payload(state,'3')?.sections||payload(state,'2')?.sections||state.imports?.['2']?.sections||[];}
function questions(state){return payload(state,'5')?.questions||[];}
function prerequisite(state,stage){
 if(stage==='1')return;
 if(stage==='3'&&state.imports?.['2']){if(!state.imports['1']&&!state.approved['1'])fail('imported architecture audit needs a requirements checklist and authoritative sources');return;}
 const prior={2:'1',3:'2',4:'3',5:'4',6:'5','7A':'6','7C':'7A',8:'7C',9:'8'}[stage];need(state,prior);
 if(['4','5','9'].includes(stage)&&!state.word_count)fail('Stage '+stage+' requires a supplied main-text word count');
 if(['5','6','7A','7C','8','9'].includes(stage))need(state,'3');
}
function inputSnapshot(state,request){
 const prior={};for(const [key,v] of Object.entries(state.approved))prior[key]=v.payload;
 // Omit only artifacts irrelevant to the requested operation, by an explicit stage dependency map.
 const relevant={1:[],2:['1'],3:['1','2'],4:['1','3'],5:['1','3','4'],6:['1','5'], '7A':['5','6'],'7C':['5','6','7A'],8:['5','6','7C'],9:['3','4','5','8']}[request.stage];
 const previous={};for(const key of relevant||[])if(prior[key]||state.imports?.[key])previous[key]=prior[key]||state.imports[key];
 if(prior[request.stage])previous[request.stage]=prior[request.stage];
 const dependencies=Object.fromEntries(Object.keys(previous).filter(k=>state.approved[k]).map(k=>[k,state.approved[k].sha]));
 const imports=Object.fromEntries(Object.keys(previous).filter(k=>!state.approved[k]&&state.imports?.[k]).map(k=>[k,hash(JSON.stringify(state.imports[k]))]));
 return {control:{workflow:'reverse_essay_scaffolding',requested_stage:request.stage,word_count:state.word_count,referencing_style:state.referencing_style,criterion_anchors:state.criterion_anchors,omissions:request.omissions,known_gaps:state.gaps},sources:state.sources,previous,dependencies,imports,answers:request.answers||{}};
}
export function scaffoldContract(snapshot,attempt=1,retry){
 const value={objective:'Perform only reverse essay scaffolding Stage '+snapshot.control.requested_stage+'. Do not write or edit answers. Stop at author review.',constraints:'Only supplied evidence. Preserve IDs, source wording and command words. Output schema: '+schemas[snapshot.control.requested_stage],evidence:JSON.stringify({...snapshot,control:{...snapshot.control,attempt}}),completed:'Source packet preserved; prerequisites and approvals checked by host.',remaining:'Requested stage only.',result:'Standard acceptance JSON plus scaffold object.',facts:[],assumptions:[],unknowns:[],references:[],acceptance:[
 {id:'A1',requirement:'Cover the declared requirements and preserve traceable supplied anchors without invented evidence or answer prose.',source_quote:'',verification:{kind:'analysis',command:''}},
 {id:'A2',requirement:'Perform only the requested stage, preserve prerequisite IDs, respect budgets and stop for author review.',source_quote:'',verification:{kind:'analysis',command:''}}]};if(retry)value.retry_failure=retry;return value;
}
export const SCAFFOLD_RETURN=' Also return scaffold:{stage:the exact requested stage string,status:AWAITING AUTHOR REVIEW|INCOMPLETE|BLOCKED,processed_anchors:[every input anchor processed],omissions:[],gaps:[{issue,blocking:boolean}],proposals:[{class:PROPOSED ADDITION,text}],quotes:[{anchor,text}],...the requested stage fields}. Every substantive record uses the supplied content classes and exact anchors. No invented IDs for sources. Generated requirement/section/question IDs must be stable and referentially valid. Do not output COMPLETE or approve your own work. Proposals remain excluded from required content.';
function packetLength(snapshot){const c=bindContract(scaffoldContract(snapshot),[]);c.scaffold_mode='reverse-v1';c.return_format=RESULT_INSTRUCTION+SCAFFOLD_RETURN;return JSON.stringify(c).replaceAll('@','\\u0040').length;}
async function begin(base,key,r){
 const parent=join(base,'reverse-scaffolds');await folder(parent);const dir=join(parent,r.run_id);await folder(dir);
 const manifest=join(dir,'manifest.json');let state;
 try{state=JSON.parse(await readFile(manifest,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;state={version:1,run_id:r.run_id,sources:[],approved:{},pending:{},imports:{},history:[],criterion_anchors:[],word_count:null,referencing_style:null,gaps:[]};}
 const draft=structuredClone(state);
 for(const s of r.sources){const old=draft.sources.find(x=>x.id===s?.id);if(old&&!same(old,s))fail('source changed; start a new run so prior approvals cannot drift');if(!old){if(draft.history.length&&s.kind!=='reference')fail('new authoritative input requires a new run');draft.sources.push(s);}}
 const anchors=validateSources(draft.sources);
 if(!draft.sources.some(s=>s.kind==='brief'))fail('an official brief is required');
 if(r.depends_on_spec===true&&!draft.sources.some(s=>s.kind==='spec'))fail('the brief depends on a missing unit specification');
 if(!draft.sources.some(s=>s.kind==='spec')&&r.brief_sufficient!==true&&draft.brief_sufficient!==true)fail('confirm brief_sufficient only when the brief independently establishes the task');
 draft.brief_sufficient=r.brief_sufficient??draft.brief_sufficient;
 for(const key of ['word_count','referencing_style'])if(r[key]!==undefined){if(draft.history.length&&draft[key]!==r[key])fail('changed assignment rules require a new run');draft[key]=r[key];}
 if(!draft.criterion_anchors.length&&!r.criterion_anchors.length)draft.criterion_anchors=[...anchors.values()].filter(a=>a.kind==='criterion'&&['brief','spec','rules'].includes(a.source_kind)).map(a=>a.id);
 if(r.criterion_anchors.length){if(draft.criterion_anchors.length&&!same(r.criterion_anchors,draft.criterion_anchors))fail('criterion inventory changed; start a new run');draft.criterion_anchors=r.criterion_anchors;}
 for(const a of draft.criterion_anchors)if(!anchors.has(a)||!['brief','spec','rules'].includes(anchors.get(a).source_kind))fail('criterion inventory must name authoritative supplied anchors');
 draft.gaps=[];if(!draft.sources.some(s=>s.kind==='spec'))draft.gaps.push('Unit specification not supplied; author declared brief independently sufficient.');
 if(!draft.word_count)draft.gaps.push('Word count not supplied.');if(!draft.referencing_style)draft.gaps.push('Referencing style not supplied.');if(!draft.sources.some(s=>s.kind==='rules'))draft.gaps.push('Separate marking/submission guidance not supplied; check brief coverage.');
 for(const sha of r.approve){
  const candidate=draft.pending[sha];if(!candidate||candidate.status!=='AWAITING AUTHOR REVIEW'||candidate.issues.length||candidate.omissions.length)fail('approval must name an eligible saved stage hash');
  for(const [stage,sha] of Object.entries(candidate.dependencies||{}))if(draft.approved[stage]?.sha!==sha)fail('approval is stale because an approved prerequisite changed');
  for(const [stage,sha] of Object.entries(candidate.imports||{}))if(hash(JSON.stringify(draft.imports[stage]))!==sha)fail('imported prerequisite changed; audit again');
  const candidateIndex=stages.indexOf(candidate.stage);
  for(const k of Object.keys(draft.approved))if(stages.indexOf(k)>candidateIndex)delete draft.approved[k];
  // All downstream pending versions are invalid after approving a changed predecessor.
  for(const [id,p] of Object.entries(draft.pending))if(stages.indexOf(p.stage)>candidateIndex)delete draft.pending[id];
  draft.approved[candidate.stage]={sha,payload:candidate.payload,approved_by:key};
  if(candidate.stage==='3'&&draft.imports['1'])draft.approved['1']={sha:hash(JSON.stringify(draft.imports['1'])),payload:draft.imports['1'],approved_by:key,import_audited:true};
 }
 if(r.imports.length){if(r.stage!=='3')fail('imports are accepted only for an explicit Stage 3 audit');for(const item of r.imports){if(!['1','2'].includes(String(item.stage))||!item.payload)fail('import only requirements and architecture, retaining imported status');draft.imports[String(item.stage)]=item.payload;}if(!draft.imports['1']&&!draft.approved['1'])fail('imported architecture requires a source-bound requirements checklist');}
 if(r.stage==='approve') {
  if(!r.approve.length)fail('supply the exact artifact hash to approve');
  const approvalDir=join(dir,key);await folder(approvalDir);
  const receipt=await writeNew(approvalDir,'approval.json',JSON.stringify({author_turn:key,approved:r.approve,status:draft.approved['8']?'COMPLETE':'APPROVED'},null,2)+'\n');
  draft.history.push({key,status:'author approval',sha:r.approve,receipt});await save(manifest,draft);
  return {run_id:r.run_id,stage:r.stage,base,folder:approvalDir,status:'APPROVED',result:{status:draft.approved['8']?'COMPLETE':'APPROVED',artifact:receipt,instruction:'Approval recorded. Wait for a separate explicit stage request.'}};
 }
 prerequisite(draft,r.stage);
 const snapshot=inputSnapshot(draft,r);
 if(r.imports.length){
  for(const stage of ['1','2'])if(draft.imports[stage]){
   const snap={...snapshot,control:{...snapshot.control,requested_stage:stage},previous:{'1':draft.approved['1']?.payload||draft.imports['1']}};
   const checked=validateScaffold(snap,draft.imports[stage]);
   if(checked.issues.length)fail('imported Stage '+stage+' is not mechanically valid: '+checked.issues.join('; '));
  }
 }
 const dirRun=join(dir,key);await folder(dirRun);const requestPath=await writeNew(dirRun,'request.json',JSON.stringify({request:r,snapshot},null,2)+'\n');
 const length=packetLength(snapshot),record={run_id:r.run_id,stage:r.stage,folder:dirRun,request_path:requestPath,request_sha:hash(await readFile(requestPath,'utf8')),status:length>12000?'INCOMPLETE':'PREFLIGHT PASSED',characters:length,base};
 await writeNew(dirRun,'preflight.json',JSON.stringify({activation:'explicit user request',stage:r.stage,characters:length,limit:12000,prerequisites:'checked',known_gaps:draft.gaps,omissions:r.omissions,status:record.status},null,2)+'\n');
 if(length>12000){await save(manifest,draft);fail('handoff is '+length+' characters, exceeding 12000; input preserved at '+requestPath+'. Select a bounded criterion in a new explicit request. Nothing was truncated.');}
 draft.history.push({key,stage:r.stage,status:'requested',folder:dirRun});await save(manifest,draft);
 if(['8','9'].includes(r.stage)){const output=hostStage(snapshot);record.result=await finishScaffold(record,'host',JSON.stringify({scaffold:output}),[],0);record.status=record.result.status;}
 return record;
}
export async function beginScaffold(base,key,r){
 try{return await begin(base,key,r);}catch(error){
  try{
   const parent=join(base,'reverse-scaffolds');await folder(parent);
   const run=join(parent,r.run_id);await folder(run);const attempt=join(run,key);await folder(attempt);
   await writeNew(attempt,'blocked-preflight.json',JSON.stringify({workflow:'reverse_essay_scaffolding',stage:r.stage,status:'BLOCKED',activation:'explicit user request',error:String(error.message),request:r},null,2)+'\n');
  }catch{} // Preserve the original error if a filesystem failure also prevents its receipt.
  throw error;
 }
}
export async function loadScaffold(record){const raw=await readFile(record.request_path,'utf8');if(hash(raw)!==record.request_sha)fail('preserved request changed');return JSON.parse(raw).snapshot;}
function hostStage(snapshot){
 const {control,previous,answers}=snapshot,q=previous['5'].questions;
 const out={stage:control.requested_stage,status:'AWAITING AUTHOR REVIEW',processed_anchors:snapshot.sources.flatMap(s=>s.anchors.map(a=>a.id)),omissions:control.omissions,gaps:[],proposals:[],quotes:[]};
 if(control.requested_stage==='8'){out.slots=q.map(x=>({question_id:x.id,text:"[Author's answer]"}));return out;}
 if(!answers||Array.isArray(answers)||Object.keys(answers).some(id=>!q.some(x=>x.id===id))||Object.values(answers).some(x=>typeof x!=='string'))fail('Stage 9 answers must map existing question IDs to author-written text');
 const complete=q.filter(x=>text(answers[x.id])&&!/\[(?:HELP NEEDED|Author.s answer|TODO|PLACEHOLDER)/i.test(answers[x.id]));
 const planned=complete.reduce((sum,x)=>sum+x.max_words,0),words=complete.reduce((sum,x)=>sum+count(answers[x.id]),0),ratio=planned?words/planned:0;
 out.progress={words_written:words,answered:complete.length,total_questions:q.length,average_words:complete.length?words/complete.length:0,planned_for_answered:planned,writing_rate_ratio:ratio,projected_final_count:planned?Math.ceil(control.word_count*ratio):null,remaining_allowance:control.word_count-words,criteria_completed:list(previous['3']?.sections).filter(s=>s.kind==='criterion'&&q.filter(x=>x.section_id===s.id).every(x=>complete.includes(x))).map(s=>s.id),completion_basis:'All numbered answer slots filled; substantive adequacy is not assessed.',word_count_method:'Whitespace-separated tokens; excludes unanswered/help placeholders. Check institutional citation and word-count rules.'};
 if(complete.length>=q.length/3&&ratio>=1.5)out.proposals=q.filter(x=>x.optional&&!x.closing&&!complete.includes(x)&&x.requirement_ids.every(id=>q.some(other=>other.id!==x.id&&!other.optional&&other.requirement_ids.includes(id)))).map(x=>({class:'PROPOSED ADDITION',question_id:x.id,action:'Consider removing this optional unanswered prompt; no removal has been applied.'}));
 return out;
}
export function validateScaffold(snapshot,out,externalIssues=[]){
 const issues=[...externalIssues],stage=snapshot.control.requested_stage,prior=snapshot.previous||{},anchors=validateSources(snapshot.sources),req=prior['1']?.requirements||[],sect=prior['3']?.sections||prior['2']?.sections||[],q=prior['5']?.questions||[];
 const reqIDs=req.map(x=>x.id),qIDs=q.map(x=>x.id),sectionIDs=sect.map(x=>x.id);
 const error=s=>issues.push(s);
 if(!out||typeof out!=='object'||Array.isArray(out))return {status:'BLOCKED',issues:[...issues,'Missing structured stage output.']};
 if(String(out.stage)!==stage)error('Response attempted a different stage.');
 if(!['AWAITING AUTHOR REVIEW','INCOMPLETE','BLOCKED'].includes(out.status))error('Model cannot approve its own output or declare COMPLETE.');
 for(const k of ['processed_anchors','omissions','gaps','proposals','quotes'])if(!Array.isArray(out[k]))error('Missing list: '+k);
 if(!setSame(list(out.processed_anchors),[...anchors.keys()]))error('Source processing inventory is incomplete or invented.');
 if(!same(list(out.omissions),snapshot.control.omissions))error('Declared omissions changed.');
 for(const x of list(out.quotes))if(!x||!text(x.text)||!anchors.get(x.anchor)?.text.includes(x.text))error('Quotation is not an exact supplied excerpt.');
 const records=(name)=>{if(!Array.isArray(out[name])){error('Missing stage collection: '+name);return [];}const original=out[name];if(original.some(x=>!x||typeof x!=='object'||Array.isArray(x)))error('Malformed records in '+name);const rows=original.filter(x=>x&&typeof x==='object'&&!Array.isArray(x));if(!unique(rows.map(x=>x?.id))&&rows.some(x=>x?.id!==undefined))error('Duplicate IDs in '+name);return rows;};
 const refs=(values,known,label)=>{if(!Array.isArray(values)||values.some(x=>!known.includes(x)))error('Unknown or invalid '+label);};
 const tagged=x=>{
  if(!x||!classes.includes(x.class)){error('Invalid content class.');return;}
  refs(x.anchors,[...anchors.keys()],'source anchor');
  if(['SOURCE STATEMENT','INTERPRETATION'].includes(x.class)&&!list(x.anchors).length)error('Source statement or interpretation lacks an anchor.');
 };
 const checkSections=rows=>{
  const criteria=req.filter(x=>x.kind==='criterion'&&x.class==='SOURCE STATEMENT');
  for(const x of rows){tagged(x);if(!/^\d+(?:\.\d+)*$/.test(x?.id)||!['introduction','criterion','conclusion'].includes(x.kind))error('Invalid section ID or kind.');refs(x?.requirement_ids,reqIDs,'requirement ID');for(const k of ['introduce','develop','evidence','conclude','boundaries'])if(!text(x?.[k]))error('Section lacks '+k);if(x?.kind==='criterion'&&!list(x.requirement_ids).some(id=>criteria.some(c=>c.id===id)))error('Assessed section lacks a criterion.');if(x?.class==='PROPOSED ADDITION')error('Unapproved additions belong in proposals, not the architecture.');}
  for(const x of rows.filter(x=>x.kind==='criterion'))if(list(x.requirement_ids).filter(id=>criteria.some(c=>c.id===id)).length!==1)error('Each assessed section must have one independently auditable criterion.');
  for(const r of criteria)if(!rows.some(x=>x.kind==='criterion'&&list(x.requirement_ids).includes(r.id)))error('Missing criterion section: '+r.id);
  for(const kind of ['introduction','conclusion'])if(rows.filter(x=>x.kind===kind).length!==1)error('Architecture requires one '+kind);
 };
 if(stage==='1'){
  const rows=records('requirements');if(!rows.some(x=>x.kind==='criterion'&&x.class==='SOURCE STATEMENT'))error('Checklist needs at least one source-bound assessment criterion.');
  for(const x of rows){tagged(x);if(!idOK(x?.id)||!['criterion','outcome','rule','mandatory','exclusion'].includes(x.kind)||typeof x.command_word!=='string')error('Invalid requirement row.');if(x.class==='SOURCE STATEMENT'&&(!text(x.source_text)||!list(x.anchors).some(a=>anchors.get(a)?.text.includes(x.source_text))))error('Requirement wording is not source-bound.');if(x.kind==='criterion'&&x.class==='SOURCE STATEMENT'){if(!text(x.command_word)||!String(x.source_text).toLowerCase().includes(String(x.command_word).toLowerCase()))error('Criterion command word is missing or changed.');if(!list(x.anchors).some(a=>anchors.get(a)?.text===x.source_text))error('Criterion wording must be copied exactly from its supplied anchor.');}if(x.class==='SOURCE STATEMENT'&&list(x.anchors).some(a=>!['brief','spec','rules'].includes(anchors.get(a)?.source_kind)))error('Requirement uses non-authoritative context as authority.');}
  for(const a of snapshot.control.criterion_anchors)if(!rows.some(x=>x.kind==='criterion'&&x.class==='SOURCE STATEMENT'&&list(x.anchors).includes(a)))error('Declared criterion missing: '+a);
 }
 if(stage==='2'||stage==='3')checkSections(records('sections'));
 if(stage==='3')for(const x of records('findings')){tagged(x);refs(x?.requirement_ids,reqIDs,'audit requirement');if(!['blocking','advisory'].includes(x?.severity)||!text(x.issue)||!text(x.resolution))error('Invalid audit finding.');if(x?.severity==='blocking')error('Blocking architecture finding: '+x.id);}
 if(stage==='4'){
  const rows=records('budgets');if(!setSame(rows.map(x=>x?.section_id),sectionIDs))error('Budget section coverage mismatch.');
  if(rows.some(x=>!Number.isSafeInteger(x?.max_words)||x.max_words<=0)||rows.reduce((n,x)=>n+(x?.max_words||0),0)!==snapshot.control.word_count)error('Section maxima do not equal the allowed total.');tagged(out.basis);if(!text(out.basis?.text))error('Missing word-count inclusion/exclusion basis.');
 }
 if(stage==='5'){
  const rows=records('questions');if(!rows.length)error('Empty question scaffold.');
  for(const x of rows){tagged(x);if(!/^\d+(?:\.\d+){1,}$/.test(x?.id)||!x.id.startsWith(x.section_id+'.')||!sectionIDs.includes(x.section_id))error('Invalid question nesting.');refs(x?.requirement_ids,reqIDs,'question requirement');if(!text(x?.text)||!Number.isSafeInteger(x.max_words)||x.max_words<=0||typeof x.optional!=='boolean'||typeof x.closing!=='boolean'||(x.task_count!==1&&x.inseparable_procedure!==true))error('Invalid question task or allowance.');if(x?.class==='PROPOSED ADDITION')error('Unapproved topic included in questions.');if(x.optional&&x.closing)error('A required closing question cannot be optional.');}
  for(const old of list(prior['5']?.questions))if(!rows.some(x=>x.id===old.id&&x.section_id===old.section_id&&same(x.requirement_ids,old.requirement_ids)))error('Existing question ID or requirement mapping changed: '+old.id);
  for(const b of list(prior['4']?.budgets))if(rows.filter(x=>x.section_id===b.section_id).reduce((n,x)=>n+x.max_words,0)!==b.max_words)error('Question word maxima mismatch: '+b.section_id);
  for(const s of sect.filter(x=>x.kind==='criterion')){const group=rows.filter(x=>x.section_id===s.id),last=group.at(-1);if(!last?.closing)error('Missing final judgement question: '+s.id);for(const id of s.requirement_ids.filter(id=>req.find(r=>r.id===id)?.kind==='criterion')){if(!group.some(x=>list(x.requirement_ids).includes(id)))error('Criterion has no question: '+id);const command=req.find(r=>r.id===id)?.command_word;if(last?.command_word!==command)error('Final command word changed: '+id);}}
 }
 if(stage==='6'){
  const rows=records('evidence');if(!setSame(rows.map(x=>x?.question_id),qIDs))error('Every question needs exactly one evidence cue.');
  for(const x of rows){if(!cues.includes(x?.cue)||!text(x.reason)||typeof x.source_type!=='string')error('Invalid evidence cue.');refs(x?.supporting_questions,qIDs,'supporting question');if(x?.cue==='Citation required'&&!text(x.source_type))error('Citation cue lacks source type.');if(x?.cue==='Evidence already cited in section'){if(!list(x.supporting_questions).length)error('Earlier evidence question is missing.');const section=q.find(a=>a.id===x.question_id)?.section_id;if(list(x.supporting_questions).some(id=>id===x.question_id||q.find(a=>a.id===id)?.section_id!==section))error('Evidence must refer to other questions in the same section.');}if(x?.cue==='UNRESOLVED GAP')error('Unresolved evidence cue: '+x.question_id);}
  for(const x of records('research_directions')){tagged(x);refs(x?.requirement_ids,reqIDs,'research requirement');}
 }
 if(stage==='7A'){const rows=records('research_directions');for(const x of rows){tagged(x);refs(x?.question_ids,qIDs,'research question');if(!text(x.claims)||!text(x.source_types))error('Research plan lacks claims/source types.');}const needs=list(prior['6']?.evidence).filter(x=>x.cue==='Citation required').map(x=>x.question_id);for(const id of needs)if(!rows.some(x=>list(x.question_ids).includes(id)))error('Research plan omits question: '+id);}
 if(stage==='7C'){
  const rows=records('mappings');for(const x of rows){const s=snapshot.sources.find(s=>s.id===x?.source_id);if(!s){error('Unknown reference source.');continue;}refs(x.question_ids,qIDs,'mapped question');refs(x.anchors,s.anchors.map(a=>a.id),'reference anchor');if(!['SUPPORTED','UNVERIFIED'].includes(x.status)||!text(x.claims)||!text(x.limits))error('Invalid source mapping.');if(x.reference!==(s.reference||'')||x.location!==(s.location||''))error('Reference metadata was invented or altered.');if(x.status==='SUPPORTED'&&(!s.verified_metadata||!text(s.reference)||!text(s.location)||!list(x.anchors).some(a=>anchors.get(a)?.kind==='passage')))error('Source support needs a supplied passage and checked metadata.');}
  for(const e of list(prior['6']?.evidence).filter(x=>x.cue==='Citation required'))if(!rows.some(x=>x.status==='SUPPORTED'&&list(x.question_ids).includes(e.question_id)))error('Required question lacks checked evidence: '+e.question_id);
 }
 if(stage==='8'){const rows=records('slots');if(!setSame(rows.map(x=>x?.question_id),qIDs)||rows.some(x=>x.text!=="[Author's answer]"))error('Answer template must contain every ID once with empty slots only.');}
 // Reject unexpected stage artifacts instead of allowing downstream work to leak into this stage.
 const stageFields={1:['requirements'],2:['sections'],3:['sections','findings'],4:['budgets','basis'],5:['questions'],6:['evidence','research_directions'],'7A':['research_directions'],'7C':['mappings'],8:['slots'],9:['progress']}[stage]||[];
 for(const k of Object.keys(out))if(!['stage','status','processed_anchors','omissions','gaps','proposals','quotes',...stageFields].includes(k))error('Unexpected stage output: '+k);
 for(const proposal of list(out.proposals))if(proposal?.class!=='PROPOSED ADDITION')error('Proposals must be labelled PROPOSED ADDITION.');
 const status=out.status==='BLOCKED'?'BLOCKED':issues.length||list(out.gaps).some(g=>!g||g.blocking!==false)||list(out.omissions).length||out.status==='INCOMPLETE'?'INCOMPLETE':'AWAITING AUTHOR REVIEW';
 return {status,issues};
}
const titles={'1':'Requirements checklist','2':'Report architecture','3':'Architecture audit','4':'Word budget','5':'Question scaffold','6':'Citation map','7A':'Research plan','7C':'Source index','8':'Author answer template','9':'Progress check'};
function render(snapshot,out,review,attempt){
 const lines=[`# ${titles[snapshot.control.requested_stage]}`, '', 'Workflow: reverse_essay_scaffolding',`Stage: ${snapshot.control.requested_stage}`,`Status: ${review.status}`,`Inputs processed: ${list(out?.processed_anchors).join(', ')||'none'}`,`Inputs not processed: ${snapshot.control.omissions.join(', ')||'none'}`,`Attempt: ${attempt?attempt+' of 2':'host operation; no model attempt'}`,'','Author review is required. Mechanical checks do not prove coverage, question atomicity or source support.',''];
 if(Array.isArray(out?.slots)){for(const row of out.slots)lines.push(`${row?.question_id} ${row?.text}`,'');}
 else for(const [name,value] of Object.entries(out||{})){if(['stage','status','processed_anchors','omissions'].includes(name))continue;lines.push('## '+name.replaceAll('_',' '),'');if(Array.isArray(value)){for(const row of value){if(!row||typeof row!=='object'){lines.push('- '+String(row));continue;}lines.push('### '+(row.id||row.question_id||row.source_id||row.section_id||'Record'),'');for(const [k,v] of Object.entries(row))lines.push(`- **${k.replaceAll('_',' ')}:** ${typeof v==='string'?v:JSON.stringify(v)}`);lines.push('');}if(!value.length)lines.push('None.','');}else lines.push('```json',JSON.stringify(value,null,2),'```','');}
 if(snapshot.control.known_gaps.length)lines.push('## Input limitations','',...snapshot.control.known_gaps.map(x=>'- '+x),'');
 if(review.issues.length)lines.push('## Failed checks','',...review.issues.map(x=>'- '+x),'');return lines.join('\n')+'\n';
}
export async function finishScaffold(record,callID,raw,sourceIssues=[],attempt=1){
 const snapshot=await loadScaffold(record);let result;try{result=JSON.parse(raw);}catch{}
 const state=await readState(record.base,record.run_id);
 const stale=[];for(const [stage,sha] of Object.entries(snapshot.dependencies||{}))if(state.approved[stage]?.sha!==sha)stale.push('Approved prerequisite changed during execution: '+stage);
 for(const [stage,sha] of Object.entries(snapshot.imports||{}))if(hash(JSON.stringify(state.imports[stage]))!==sha)stale.push('Imported prerequisite changed during execution: '+stage);
 const out=result?.scaffold;let review;
 try{review=validateScaffold(snapshot,out,[...sourceIssues,...stale]);}catch{review={status:'BLOCKED',issues:[...sourceIssues,...stale,'Malformed stage data prevented validation; no approval available.']};}
 const artifact={stage:record.stage,payload:out||null,status:review.status,issues:review.issues,omissions:snapshot.control.omissions,request_sha:record.request_sha,dependencies:snapshot.dependencies,imports:snapshot.imports,attempt};
 const sha=hash(JSON.stringify(artifact));const name=hash(callID).slice(0,16);
 const jsonPath=await writeNew(record.folder,'stage-'+record.stage+'-'+name+'.json',JSON.stringify({...artifact,sha,raw_result:raw},null,2)+'\n');
 const markdown=await writeNew(record.folder,'stage-'+record.stage+'-'+name+'.md',render(snapshot,out,review,attempt));
 state.pending[sha]={...artifact,artifact:jsonPath,markdown};
 state.history.push({stage:record.stage,sha,status:review.status,artifact:jsonPath});await save(join(record.base,'reverse-scaffolds',record.run_id,'manifest.json'),state);
 return {...review,stage:record.stage,run_id:record.run_id,artifact:jsonPath,markdown,approval_sha:review.status==='AWAITING AUTHOR REVIEW'?sha:null,processed:snapshot.sources.map(s=>s.id),omissions:snapshot.control.omissions,instruction:'Stop here. A later explicit author approval of this exact hash is required. Do not advance stages or draft answers.'};
}
