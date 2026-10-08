// Host-side essay contract. No inference, external services or model tools.
import {mkdir,lstat,open,readFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {createHash} from 'node:crypto';
export const PREFIX='ESSAY_EDIT\n';
const digest=s=>createHash('sha256').update(s).digest('hex');
const fail=s=>{throw Error('Essay edit: '+s);};
export function parseRequest(parts){
  const text=parts.filter(p=>p.type==='text'&&!p.synthetic).map(p=>p.text).join('\n');
  if(!text.startsWith(PREFIX))return null;
  let request;try{request=JSON.parse(text.slice(PREFIX.length));}catch{fail('supply a JSON object with draft and optional author_request, constraints, source_material, reorder and randomiser');}
  if(!request||Array.isArray(request)||typeof request!=='object')fail('invalid request');
  if(Object.keys(request).some(k=>!['draft','author_request','constraints','source_material','reorder','randomiser'].includes(k)))fail('unknown request option');
  for(const k of ['draft','author_request','constraints','source_material']){
    if(request[k]===undefined&&k!=='draft')request[k]='';
    if(typeof request[k]!=='string')fail(k+' must be text');
  }
  if(!request.draft.trim())fail('the draft is empty');
  if(request.draft.length>30000)fail('draft exceeds submission limit; supply an explicitly scoped section');
  if(['author_request','constraints','source_material'].some(k=>request[k].length>3000))fail('supporting input exceeds 3000 characters');
  request.reorder??='none';request.randomiser??=false;
  if(!['none','local','structural'].includes(request.reorder)||typeof request.randomiser!=='boolean')fail('invalid reordering or randomiser option');
  return request;
}
export function paragraphs(draft){return draft.split(/\r?\n[ \t]*\r?\n/).filter(p=>p.trim()).map((text,i)=>({id:'P'+(i+1),text}));}
export async function writeNew(folder,name,content){
  await mkdir(folder,{recursive:true,mode:0o700});
  const info=await lstat(folder);if(!info.isDirectory()||info.isSymbolicLink())fail('output folder must not be a symlink');
  const path=join(folder,name),handle=await open(path,'wx',0o600);
  try{await handle.writeFile(content);await handle.sync();}finally{await handle.close();}
  return path;
}
export async function preserve(directory,key,request){
  const parent=join(resolve(directory),'.local-ai-essays');
  await mkdir(parent,{recursive:true,mode:0o700});
  if((await lstat(parent)).isSymbolicLink())fail('essay directory must not be a symlink');
  const folder=join(parent,key);await mkdir(folder,{mode:0o700});
  await writeNew(folder,'essay.original.md',request.draft);
  const original=await readFile(join(folder,'essay.original.md'),'utf8');
  if(original!==request.draft)fail('original copy verification failed');
  await writeNew(folder,'request.json',JSON.stringify(request,null,2)+'\n');
  return {folder,sha256:digest(original),request_sha256:digest(JSON.stringify(request)),status:'preserved'};
}
export async function loadRequest(record){
  const request=JSON.parse(await readFile(join(record.folder,'request.json'),'utf8'));
  if(digest(JSON.stringify(request))!==record.request_sha256||digest(await readFile(join(record.folder,'essay.original.md'),'utf8'))!==record.sha256)fail('saved original or permissions changed');
  return request;
}
export function makeContract(request,retry){
  const value={objective:'Copyedit the explicitly submitted essay using the installed essay instructions. Return every paragraph by stable ID. Do not summarise.',
    constraints:JSON.stringify({author_request:request.author_request,constraints:request.constraints,reorder:request.reorder,randomiser:request.randomiser,random_selection:'not performed; optional alternatives in notes only'}),
    evidence:JSON.stringify({draft:paragraphs(request.draft),source_material:request.source_material}),completed:'Original preserved by host.',remaining:'Edit all supplied paragraphs and provide editorial notes.',result:'Return the standard acceptance JSON plus essay as instructed.',
    facts:[],assumptions:[],unknowns:[],references:[],acceptance:[
      {id:'A1',requirement:'Preserve all substantive content, protected text, meaning and qualifications; do not invent evidence.',source_quote:'',verification:{kind:'analysis',command:''}},
      {id:'A2',requirement:'Respect explicit reordering scope; diagnose rhythm without forcing templates; keep editorial notes outside prose.',source_quote:'',verification:{kind:'analysis',command:''}}]};
  if(retry)value.retry_failure=retry;
  return value;
}
export const RETURN_INSTRUCTION=' Also return essay:{paragraphs:[{id:"P1",text:"complete edited paragraph",removed_notes:[],beats:"A+C"}],editorial_notes:"all five required categories and verification limits",moves:[{from:"P1",to:"P2",purpose:"...",dependencies:"...",validation:"..."}]}. Return each supplied paragraph ID exactly once. Never duplicate the essay in summary. Only explicit drafting notes may be removed; put their exact text in removed_notes. Keep a record even if a note-only paragraph becomes empty. Beat labels are editorial judgements. No tools, file reads or file writes. At most two rhythm alternatives may appear in notes when requested; host random selection is not implemented. Never claim it was performed.';
const counts=a=>{const m=new Map();for(const s of a)m.set(s,(m.get(s)||0)+1);return [...m].sort(([a],[b])=>a.localeCompare(b));};
const extract=(s,re)=>[...s.matchAll(re)].map(m=>m[0]);
function protectedText(s){return {
 quotes:extract(s,/"[^"]+"|“[^”]+”|‘[^’]+’|(?<![\p{L}\p{N}])'[^'\n]+'(?![\p{L}\p{N}])/gu),
 numbers:extract(s,/(?<![\p{L}\p{N}])[-+]?\d+(?:[.,]\d+)*(?:%|\b)/gu),
 units:extract(s,/\b\d+(?:[.,]\d+)*\s*(?:kg|mg|km|cm|mm|mL|ml|kWh|GHz|MHz|GB|MB|°C|°F|hours?|minutes?|seconds?|years?)\b/g),
 citations:extract(s,/\[[^\]\n]+\]|\([^()\n]*\b(?:19|20)\d{2}[a-z]?[^()\n]*\)|https?:\/\/[^\s)]+/g),
 qualifications:extract(s,/\b(?:may|might|can|could|often|sometimes|suggests?|possibly|probably|unlikely|not|never|no|unless|only|if)\b/gi).map(x=>x.toLowerCase())};}
export function validateEdit(request,result,sourceIssues=[]){
  const issues=[...sourceIssues],source=paragraphs(request.draft),essay=result?.essay;
  if(!essay||!Array.isArray(essay.paragraphs)||typeof essay.editorial_notes!=='string'||!essay.editorial_notes.trim()||!Array.isArray(essay.moves))return {issues:[...issues,'Missing essay output or editorial notes.'],status:'incomplete'};
  const rows=essay.paragraphs;
  for(const label of ['Uncertain quotations','Unsupported claims','Meaning or structure concerns','Drafting notes and placeholders','Rhythm findings'])
    if(!essay.editorial_notes.toLowerCase().includes(label.toLowerCase()))issues.push('Missing notes category: '+label);
  if(rows.length!==source.length||new Set(rows.map(p=>p?.id)).size!==source.length||rows.some(p=>!source.some(s=>s.id===p?.id)))issues.push('Missing, duplicated or unknown paragraphs.');
  if(request.reorder!=='structural'&&JSON.stringify(rows.map(p=>p?.id))!==JSON.stringify(source.map(p=>p.id)))issues.push('Paragraph order changed without structural permission.');
  for(const s of source){
    const row=rows.find(p=>p?.id===s.id);
    if(!row||typeof row.text!=='string'||!Array.isArray(row.removed_notes)||row.removed_notes.some(n=>typeof n!=='string'||!n.trim()||!s.text.includes(n))){issues.push('Invalid paragraph or removed-note record: '+s.id);continue;}
    if(typeof row.beats!=='string'||!/^([DENCSQAPRT?](\+[DENCSQAPRT?])*)( → [DENCSQAPRT?](\+[DENCSQAPRT?])*)*$/.test(row.beats))issues.push('Missing or invalid rhythm map: '+s.id);
    // Only explicitly marked note blocks are eligible for removal, never arbitrary prose.
    let comparable=s.text;
    for(const n of row.removed_notes){if(!/^\[(?:TODO|NOTE|DRAFT NOTE|PLACEHOLDER):[\s\S]*\]$/i.test(n)){issues.push('Unmarked content removed as a drafting note: '+s.id);continue;}comparable=comparable.replace(n,'');}
    const a=protectedText(comparable),b=protectedText(row.text);
    for(const k of Object.keys(a))if(JSON.stringify(counts(a[k]))!==JSON.stringify(counts(b[k])))issues.push('Changed '+k+' in '+s.id);
    if(comparable.trim()&&!row.text.trim())issues.push('Substantive paragraph omitted: '+s.id);
    if(comparable.length>120&&row.text.length<comparable.length*.65)issues.push('Possible abridgement: '+s.id);
    if(/\[(?:omitted|rest unchanged|continue here)\]|\.\.\./i.test(row.text)&&!s.text.includes(row.text))issues.push('Possible incomplete placeholder: '+s.id);
  }
  if(request.reorder==='none'&&essay.moves.length)issues.push('Reordering reported without permission.');
  for(const m of essay.moves)if(!m||['from','to','purpose','dependencies','validation'].some(k=>typeof m[k]!=='string'||!m[k].trim()))issues.push('Incomplete move record.');
  if(request.reorder==='local')for(const m of essay.moves){
    if(!/^P\d+\.s\d+$/.test(m?.from)||!/^P\d+\.s\d+$/.test(m?.to)||m.from.split('.')[0]!==m.to.split('.')[0])issues.push('Local move exceeds its paragraph scope.');
  }
  if(request.reorder==='structural'&&JSON.stringify(rows.map(p=>p.id))!==JSON.stringify(source.map(p=>p.id))&&!essay.moves.length)issues.push('Structural move lacks dependency record.');
  return {issues,status:issues.length?'needs_attention':'review_required',edited:rows.filter(p=>typeof p?.text==='string'&&p.text.trim()).map(p=>p.text).join('\n\n'),notes:essay.editorial_notes,
    rhythm:rows.map(p=>({id:p?.id,beats:p?.beats})),moves:essay.moves,
    removed_notes:rows.flatMap(p=>(Array.isArray(p?.removed_notes)?p.removed_notes:[]).map(text=>({id:p.id,text}))),
    limitation:'Mechanical checks do not prove semantic equivalence, factual accuracy, citation attachment or sentence-order preservation. Author review is required.'};
}
export async function persistResult(record,callID,request,raw,sourceIssues){
  let result;try{result=JSON.parse(raw);}catch{}
  const review=validateEdit(request,result,sourceIssues);
  const suffix=digest(callID).slice(0,16),notesName='essay.'+suffix+'.editorial-notes.md';
  const notes=[review.notes||'No complete editorial notes returned.', '\nHost review: '+review.status,
    ...(review.issues||[]).map(x=>'- '+x), '\n'+(review.limitation||'Incomplete model response; no edited essay released.'),
    '\nRemoved drafting notes: '+JSON.stringify(review.removed_notes||[]),
    '\nRhythm map: '+JSON.stringify(review.rhythm||[]),'\nMoves: '+JSON.stringify(review.moves||[]),
    '\nRandomiser: '+(request.randomiser?'requested; labelled alternatives only, no host random selection performed.':'off.')].join('\n');
  const notesPath=await writeNew(record.folder,notesName,notes+'\n');
  let editedPath=null;
  if(review.status==='review_required')editedPath=await writeNew(record.folder,'essay.'+suffix+'.edited.md',review.edited+'\n');
  await writeNew(record.folder,'review.'+suffix+'.json',JSON.stringify({...review,raw_result:raw},null,2)+'\n');
  return {status:review.status,original:join(record.folder,'essay.original.md'),edited:editedPath,editorial_notes:notesPath,issues:review.issues,limitation:review.limitation};
}
