"""System prepares resident changes; only the authenticated owner publishes them.

No model calls, scheduler, tools, grant expansion or activation occur while
preparing proposals. Pending directions never enter a resident's memory packet.
"""
import json
import re
import time
import uuid

import village
import village_memory as memory
from village_infrastructure import bounded,encoded,sha


def initialize(cx):
    memory.initialize(cx)
    if cx.execute("SELECT 1 FROM sqlite_master WHERE name='resident_management_schema'").fetchone():
        if [r[0] for r in cx.execute('SELECT version FROM resident_management_schema')]!=[1]:raise RuntimeError('Unsupported resident management schema')
        return
    with cx:
        cx.execute('BEGIN IMMEDIATE')
        cx.execute('CREATE TABLE resident_management_schema(version INTEGER PRIMARY KEY)')
        cx.execute('INSERT INTO resident_management_schema VALUES(1)')
        cx.execute('''CREATE TABLE resident_changes(id TEXT PRIMARY KEY,digest TEXT UNIQUE NOT NULL,
            kind TEXT NOT NULL,resident TEXT NOT NULL,payload TEXT NOT NULL,reason TEXT NOT NULL,
            author TEXT NOT NULL,created INTEGER NOT NULL,expires INTEGER NOT NULL)''')
        cx.execute('''CREATE TABLE resident_change_decisions(digest TEXT PRIMARY KEY,
            state TEXT NOT NULL,result TEXT NOT NULL)''')


def _profile_binding(cx,sid):
    row=village.specialist(cx,sid)
    if not memory.access(cx,sid,[]):raise PermissionError('Resident lineage unavailable')
    profile=cx.execute('SELECT * FROM profiles WHERE specialist_id=? ORDER BY revision DESC LIMIT 1',(sid,)).fetchone()
    return dict(id=sid,parent=row['parent_id'],role=row['role'],tags=json.loads(row['tags']),revision=profile['revision'],instruction=profile['instruction'],collections=sorted(village.grants(cx,sid)))


def _profile(cx,kind,p):
    allowed={'id','parent','role','tags','instruction','status'} if kind=='create' else {'id','tags','instruction'} if kind=='revise' else {'id'}
    if not isinstance(p,dict) or set(p)-allowed or not isinstance(p.get('id'),str) or not village.ID.fullmatch(p['id']):raise ValueError('Invalid resident change')
    if kind=='create':
        if p.get('role') not in village.ROLES or not isinstance(p.get('parent'),str):raise ValueError('Choose an existing role and active parent')
        base=_profile_binding(cx,p['parent'])
        if base['role']!=p['role'] or 'general' not in base['collections']:raise PermissionError('Parent role or General grant unavailable')
        if cx.execute('SELECT 1 FROM specialists WHERE id=?',(p['id'],)).fetchone():raise ValueError('Resident already exists')
        status=p.get('status','active')
        if status not in ('active','experimental'):raise ValueError('Invalid proposed lifecycle state')
        result=dict(id=p['id'],parent=p['parent'],role=p['role'],status=status)
    else:
        base=_profile_binding(cx,p['id'])
        if not base['parent']:raise PermissionError('Built-in residents cannot be revised or retired by management proposals')
        if kind=='retire' and cx.execute("SELECT 1 FROM specialists WHERE parent_id=? AND status='active'",(p['id'],)).fetchone():raise ValueError('Review active daughters before retiring their parent')
        # Agent management is general-only; private specialisms need deliberate owner scope work.
        if set(base['collections'])!={'general'}:raise PermissionError('Automatic resident changes require General-only grants')
        result=dict(id=p['id'])
    if kind!='retire':
        tags=p.get('tags',[])
        if not isinstance(tags,list) or len(tags)>12 or any(not isinstance(t,str) or not village.ID.fullmatch(t) for t in tags):raise ValueError('Invalid specialist tags')
        instruction=bounded(p.get('instruction'),1200,'specialist instructions')
        result.update(tags=sorted(set(tags)),instruction=instruction)
    return dict(spec=result,base=base)


def _store(cx,kind,sid,payload,reason,author):
    bounded(reason,600,'reason');bounded(author,80,'author')
    digest=sha(encoded(dict(kind=kind,resident=sid,payload=payload)))
    old=cx.execute('SELECT id FROM resident_changes WHERE digest=?',(digest,)).fetchone()
    decision=cx.execute('SELECT state FROM resident_change_decisions WHERE digest=?',(digest,)).fetchone()
    if decision:return dict(state=decision[0],digest=digest,duplicate=True)
    if old:return dict(state='pending',id=old[0],digest=digest,duplicate=True)
    if cx.execute('SELECT count(*) FROM resident_changes').fetchone()[0]>=256:raise ValueError('Review or discard pending resident changes before preparing more')
    pid='change:'+uuid.uuid4().hex;now=int(time.time())
    cx.execute('INSERT INTO resident_changes VALUES(?,?,?,?,?,?,?,?,?)',(pid,digest,kind,sid,encoded(payload),reason,author,now,now+7*86400))
    return dict(state='pending',id=pid,digest=digest)


def prepare(cx,author,payload):
    """Called inside the host's receipt transaction. Cannot publish any changes."""
    if not isinstance(payload,dict) or set(payload)-{'operation','resident','spec','reason'}:raise ValueError('Invalid management request')
    operation=payload.get('operation');reason=payload.get('reason')
    if operation=='map':
        sid=payload.get('resident');preview=memory.preview_map(cx,sid,payload.get('spec'))
        if any(set(e['scopes'])-{'general'} for entries in preview['body'].values() for e in entries):raise PermissionError('Captain proposals can only reference General material')
        value=dict(spec=preview['spec'],preview_digest=preview['digest'],base_revision=preview['base_revision'],resolved=preview['resolved'])
    elif operation in ('create','revise','retire'):
        value=_profile(cx,operation,payload.get('spec'));sid=value['spec']['id']
    else:raise ValueError('Propose create, revise, retire or map; owner approval is unavailable to agents')
    return _store(cx,operation,sid,value,reason,author)


def _words(text):return set(re.findall(r'[a-z0-9]+',text.lower()))


def _suggest_map(cx,sid):
    profile=_profile_binding(cx,sid);current=memory.starting_map(cx,sid);packet=memory.packet(cx,sid,profile['collections'])
    # Preserve valid owner choices; drop stale bindings rather than silently rebinding.
    spec=dict(fast_access=[],glossary=[],preferred_sources=[])
    for layer,items in (('fast_access',packet['fast_access']),('glossary',packet['glossary']),('preferred_sources',packet['preferred_sources'])):
        for e in items:spec[layer].append({k:v for k,v in e.items() if k in ('label','target','when','query','collections')})
    labels={e['label'] for entries in spec.values() for e in entries}
    targets={e['target'] for entries in spec.values() for e in entries}
    def add(layer,target,label,when='',query=''):
        if target in targets or len(spec[layer])>=memory.MAP_LIMITS[layer]:return
        label=label[:52] or 'Reference';stem=label;number=2
        while label in labels:label=stem[:48]+' '+str(number);number+=1
        item=dict(target=target,label=label,when=when[:160])
        if query:item['query']=query
        trial=json.loads(encoded(spec));trial[layer].append(item)
        try:memory.preview_map(cx,sid,trial)
        except (ValueError,PermissionError):return
        spec[layer].append(item);targets.add(target);labels.add(label)
    rows=list(cx.execute("SELECT * FROM resident_memories WHERE specialist_id=? AND state='approved' ORDER BY created,id LIMIT 100",(sid,)))
    # Procedure/correction candidates get priority, but nothing is pinned without owner approval.
    rows.sort(key=lambda r:(r['kind'] not in ('procedure','revised_belief'),r['created'],r['id']))
    for r in rows:
        if not set(json.loads(r['scopes']))<=set(profile['collections']) or not memory.live_evidence(cx,json.loads(r['evidence'])):continue
        layer='fast_access' if r['kind'] in ('procedure','revised_belief') and len(spec['fast_access'])<3 else 'glossary'
        add(layer,r['id'],r['claim'][:52],r['applicability'])
    for r in cx.execute("SELECT * FROM resident_pointers WHERE specialist_id=? AND state='approved' ORDER BY created,id LIMIT 50",(sid,)):
        if set(json.loads(r['scopes']))<=set(profile['collections']):add('preferred_sources',r['target'],r['purpose'][:52],r['purpose'])
    synonyms={'writer':'writing humaniser humanizer editing style essay','coder':'coding code python r sql debugging programming','researcher':'research sources evidence','analyst':'analysis statistics reasoning','reviewer':'review verification checking'}
    terms=_words(' '.join(profile['tags'])+' '+profile['instruction']+' '+synonyms[profile['role']])
    docs=[]
    for r in cx.execute("SELECT id,title,collection FROM library_documents WHERE state='approved' ORDER BY created,id LIMIT 200"):
        score=len(_words(r['title'])&terms)
        if score and r['collection'] in profile['collections']:docs.append((score,r['id'],r['title']))
    for _,ref,title in sorted(docs,key=lambda r:(-r[0],r[1])):add('preferred_sources',ref,title,'Relevant to this specialism')
    if spec==current['spec']:return None
    preview=memory.preview_map(cx,sid,spec)
    return dict(spec=preview['spec'],preview_digest=preview['digest'],base_revision=preview['base_revision'],resolved=preview['resolved'])


def maintain(cx,residents=None):
    """Bounded bookkeeping from approved inputs, never inference or publication."""
    initialize(cx)
    ids=residents or [r[0] for r in cx.execute("SELECT id FROM specialists WHERE status='active' ORDER BY id LIMIT 128")]
    with cx:
        cx.execute('BEGIN IMMEDIATE')
        cx.execute('DELETE FROM resident_changes WHERE expires<?',(int(time.time()),))
        for sid in ids:
            if cx.execute('SELECT count(*) FROM resident_changes').fetchone()[0]>=256:break
            try:value=_suggest_map(cx,sid)
            except (ValueError,PermissionError):continue
            if not value:continue
            # A newer system draft replaces its own obsolete pending draft, never an agent's explicit proposal.
            cx.execute("DELETE FROM resident_changes WHERE kind='map' AND resident=? AND author='system' AND payload!=?",(sid,encoded(value)))
            _store(cx,'map',sid,value,'Prepared from this resident’s approved memories, material pointers and matching Library titles. Existing valid owner choices are retained.','system')
    return pending(cx)


def pending(cx):
    initialize(cx)
    return [dict(r) for r in cx.execute('SELECT * FROM resident_changes WHERE expires>=? ORDER BY created,id LIMIT 256',(int(time.time()),))]


def review(cx,pid,digest,decision):
    initialize(cx)
    if decision not in ('approve','reject'):raise ValueError('Choose approve or reject')
    with cx:
        cx.execute('BEGIN IMMEDIATE')
        old=cx.execute('SELECT state,result FROM resident_change_decisions WHERE digest=?',(digest,)).fetchone()
        if old:
            if old['state']!=decision:raise ValueError('Change already decided')
            return json.loads(old['result'])
        r=cx.execute('SELECT * FROM resident_changes WHERE id=? AND digest=? AND expires>=?',(pid,digest,int(time.time()))).fetchone()
        if not r:raise ValueError('Review the current unexpired proposal')
        p=json.loads(r['payload']);kind=r['kind'];sid=r['resident']
        result=dict(id=pid,resident=sid,kind=kind,state=decision)
        if decision=='approve':
            if kind=='map':
                # Inline the approved write so proposal receipt and map revision commit atomically.
                preview=memory.preview_map(cx,sid,p['spec'])
                if preview['digest']!=p['preview_digest']:raise ValueError('Map or source changed; refresh the prepared suggestion')
                revision=preview['base_revision']+1;values=(sid,revision,encoded(preview['body']),preview['digest'],'Owner approved prepared map '+pid,int(time.time()))
                cx.execute('INSERT INTO resident_starting_maps VALUES(?,?,?,?,?,?) ON CONFLICT(specialist_id) DO UPDATE SET revision=excluded.revision,body=excluded.body,digest=excluded.digest,approval=excluded.approval,created=excluded.created',values)
                cx.execute('INSERT INTO resident_starting_map_revisions VALUES(?,?,?,?,?,?)',values);result['revision']=revision
            else:
                current=_profile(cx,kind,p['spec'])
                if current!=p:raise ValueError('Resident or parent changed; request a fresh proposal')
                s=p['spec'];now=int(time.time());approval='Owner approved '+pid
                if kind=='create':
                    cx.execute('INSERT INTO specialists VALUES(?,?,?,?,?,?,?)',(sid,s['parent'],s['role'],s['status'],encoded(s['tags']),now,approval))
                    cx.execute('INSERT INTO profiles VALUES(?,?,?,?,?)',(sid,1,s['instruction'],now,approval))
                    cx.execute("INSERT INTO grants VALUES(?,'general')",(sid,))
                    result['status']=s['status']
                elif kind=='revise':
                    cx.execute('INSERT INTO profiles VALUES(?,?,?,?,?)',(sid,p['base']['revision']+1,s['instruction'],now,approval))
                    cx.execute('UPDATE specialists SET tags=? WHERE id=?',(encoded(s['tags']),sid))
                else:cx.execute("UPDATE specialists SET status='retired' WHERE id=?",(sid,))
            village.audit(cx,'resident_change',sid,'Owner approved exact '+pid)
        cx.execute('INSERT INTO resident_change_decisions VALUES(?,?,?)',(digest,decision,encoded(result)))
        cx.execute('DELETE FROM resident_changes WHERE id=?',(pid,))
        return result
