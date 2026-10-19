"""Approved documents, individual experience and explicit navigation.

Commons quarantine is never searched here. Evidence snapshots enter these
tables only as part of an exact owner-approved proposal.
"""
import json
import time
import uuid

from village import audit, grants, specialist


def exists(cx):
    return bool(cx.execute("SELECT 1 FROM sqlite_master WHERE name='resident_memory_schema'").fetchone())


def initialize(cx):
    if exists(cx):
        if [r[0] for r in cx.execute("SELECT version FROM resident_memory_schema")] != [1]:
            raise RuntimeError("Unsupported resident memory schema")
        return
    with cx:
        cx.execute("BEGIN IMMEDIATE")
        for sql in (
            "CREATE TABLE resident_memory_schema(version INTEGER PRIMARY KEY)",
            "INSERT INTO resident_memory_schema VALUES(1)",
            """CREATE TABLE library_documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,
                markdown TEXT NOT NULL,collection TEXT NOT NULL,evidence TEXT NOT NULL,
                digest TEXT NOT NULL,state TEXT NOT NULL,created INTEGER NOT NULL,approval TEXT NOT NULL)""",
            """CREATE TABLE resident_memories(id TEXT PRIMARY KEY,specialist_id TEXT NOT NULL REFERENCES specialists(id),
                kind TEXT NOT NULL,claim TEXT NOT NULL,applicability TEXT NOT NULL,scopes TEXT NOT NULL,
                evidence TEXT NOT NULL,digest TEXT NOT NULL,state TEXT NOT NULL,created INTEGER NOT NULL,approval TEXT NOT NULL)""",
            """CREATE TABLE resident_pointers(id TEXT PRIMARY KEY,specialist_id TEXT NOT NULL REFERENCES specialists(id),
                target TEXT NOT NULL,purpose TEXT NOT NULL,scopes TEXT NOT NULL,digest TEXT NOT NULL,
                state TEXT NOT NULL,created INTEGER NOT NULL,approval TEXT NOT NULL)""",
            """CREATE TABLE commons_approvals(proposal_id TEXT PRIMARY KEY,digest TEXT NOT NULL,result TEXT NOT NULL)""",
            """CREATE TABLE resident_memory_revisions(reference TEXT NOT NULL,revision INTEGER NOT NULL,
                record TEXT NOT NULL,PRIMARY KEY(reference,revision))""",
        ):
            cx.execute(sql)


def access(cx, sid, scopes):
    specialist(cx, sid)
    visited, current = set(), sid
    while current:
        if current in visited:
            raise PermissionError("Lineage cycle")
        visited.add(current)
        current = specialist(cx, current)["parent_id"]
    return set(scopes) <= grants(cx, sid)


def document_search(cx, sid, query, scopes, limit=5):
    if not exists(cx):
        return []
    allowed = grants(cx, sid) & set(scopes)
    if not allowed or not isinstance(query, str) or len(query) > 300:
        return []
    match = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = cx.execute("""SELECT id AS citation,title,collection,created,'document' AS role,
        substr(markdown,1,600) AS excerpt FROM library_documents WHERE state='approved'
        AND collection IN (""" + ",".join("?" for _ in allowed) + """ )
        AND (title LIKE ? ESCAPE '\\' OR markdown LIKE ? ESCAPE '\\') ORDER BY created DESC,id LIMIT ?""",
        (*sorted(allowed), match, match, min(10, max(1, limit))))
    return [dict(r) for r in rows]


def document_read(cx, sid, reference, scopes, *, owner=False):
    if not exists(cx):
        raise PermissionError("Document unavailable")
    row = cx.execute("SELECT * FROM library_documents WHERE id=? AND state='approved'", (reference,)).fetchone()
    if not row or row["collection"] not in scopes or (not owner and not access(cx, sid, [row["collection"]])):
        raise PermissionError("Document unavailable")
    return dict(citation=row["id"], title=row["title"], text=row["markdown"], collection=row["collection"],
                role="document", created=row["created"], digest=row["digest"])


def live_evidence(cx, evidence, _seen=None):
    seen=set() if _seen is None else _seen
    for source in evidence:
        for origin in set([source.get('origin','')]+source.get('dependencies',[])):
            if origin.startswith("msg:"):
                r = cx.execute("SELECT active,collection FROM messages WHERE citation=?", (origin,)).fetchone()
                if not r or not r["active"] or r["collection"] not in source["scopes"]:
                    return False
            elif origin.startswith("doc:"):
                r = cx.execute("SELECT state,collection FROM library_documents WHERE id=?", (origin,)).fetchone()
                if not r or r["state"] != "approved" or r["collection"] not in source["scopes"]:
                    return False
            elif origin.startswith('memory:'):
                r=cx.execute("SELECT state,scopes,evidence FROM resident_memories WHERE id=?",(origin,)).fetchone()
                if not r or r['state']!='approved' or not set(json.loads(r['scopes']))<=set(source['scopes']) or origin in seen:return False
                if not live_evidence(cx,json.loads(r['evidence']),seen|{origin}):return False
    return True


def packet(cx, sid, scopes):
    if not exists(cx):
        return dict(memories=[], pointers=[])
    specialist(cx, sid)
    allowed = grants(cx, sid) & set(scopes)
    if not access(cx,sid,allowed):
        raise PermissionError("Resident unavailable")
    memories, pointers = [], []
    for row in cx.execute("SELECT * FROM resident_memories WHERE specialist_id=? AND state='approved' ORDER BY created DESC,id LIMIT 50", (sid,)):
        if set(json.loads(row["scopes"])) <= allowed and live_evidence(cx, json.loads(row["evidence"])):
            memories.append(dict(id=row["id"], kind=row["kind"], claim=row["claim"][:500],
                                 applicability=row["applicability"][:200], created=row["created"]))
        if len(memories) == 3:
            break
    for row in cx.execute("SELECT * FROM resident_pointers WHERE specialist_id=? AND state='approved' ORDER BY created DESC,id LIMIT 30", (sid,)):
        if set(json.loads(row["scopes"])) <= allowed:
            target = row["target"]
            try:
                if target.startswith("doc:"):
                    document_read(cx, sid, target, allowed)
                else:
                    from village import read
                    read(cx, sid, target, request_collections=allowed)
            except PermissionError:
                continue
            pointers.append(dict(id=row["id"], target=target, purpose=row["purpose"][:300]))
        if len(pointers) == 3:
            break
    return dict(memories=memories, pointers=pointers)


def search_memories(cx,sid,query,scopes):
    if not exists(cx): return []
    if not isinstance(query,str) or not query.strip() or len(query)>300: raise ValueError("Memory query requires 1 to 300 characters")
    if not access(cx,sid,set(scopes)&grants(cx,sid)): raise PermissionError("Resident unavailable")
    needle='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    found=[]
    for r in cx.execute("""SELECT * FROM resident_memories WHERE specialist_id=? AND state='approved'
        AND (claim LIKE ? ESCAPE '\\' OR applicability LIKE ? ESCAPE '\\') ORDER BY created DESC LIMIT 100""",(sid,needle,needle)):
        if set(json.loads(r['scopes']))<=set(scopes)&grants(cx,sid) and live_evidence(cx,json.loads(r['evidence'])):
            found.append(dict(citation=r['id'],kind=r['kind'],claim=r['claim'][:600],applicability=r['applicability'][:200],created=r['created']))
        if len(found)==5:break
    return found


def read_memory(cx,sid,reference,scopes,owner=False):
    if not exists(cx): raise PermissionError('Memory unavailable')
    r=cx.execute("SELECT * FROM resident_memories WHERE id=? AND state='approved'",(reference,)).fetchone()
    if not r or not set(json.loads(r['scopes']))<=set(scopes) or (not owner and (r['specialist_id']!=sid or not access(cx,sid,json.loads(r['scopes'])))) or not live_evidence(cx,json.loads(r['evidence'])):
        raise PermissionError('Memory unavailable')
    return dict(citation=r['id'],title=r['kind'],text=json.dumps(dict(claim=r['claim'],applicability=r['applicability'],evidence=json.loads(r['evidence'])),ensure_ascii=False),
                role='memory',collection=json.loads(r['scopes']),created=r['created'])


def approve(cx, proposal, snapshots, approval, target=None):
    """Caller owns review; one transaction makes retry after a crash idempotent."""
    initialize(cx)
    with cx:
        cx.execute("BEGIN IMMEDIATE")
        old = cx.execute("SELECT * FROM commons_approvals WHERE proposal_id=?", (proposal["id"],)).fetchone()
        if old:
            if old["digest"] != proposal["digest"]:
                raise ValueError("Approval content changed")
            return json.loads(old["result"])
        sid, scopes, p = proposal["actor"], proposal["scopes"], proposal["payload"]
        if not access(cx, sid, scopes) or not live_evidence(cx, snapshots):
            raise PermissionError("Source or specialist scope was revoked")
        now = int(time.time())
        kind = proposal["kind"]
        evidence = json.dumps(snapshots, ensure_ascii=False)
        if kind == "memory":
            ref = "memory:" + uuid.uuid4().hex
            cx.execute("INSERT INTO resident_memories VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (ref,sid,p["kind"],p["text"],p["purpose"],json.dumps(scopes),evidence,
                        proposal["digest"],"approved",now,approval))
            record=dict(cx.execute('SELECT * FROM resident_memories WHERE id=?',(ref,)).fetchone())
            cx.execute('INSERT INTO resident_memory_revisions VALUES(?,?,?)',(ref,1,json.dumps(record)))
        elif kind == "pointer":
            if not target or not target.startswith(("doc:", "msg:")):
                raise ValueError("Approve the referenced material first")
            if target.startswith("doc:"):
                document_read(cx, sid, target, scopes)
            else:
                from village import read
                read(cx, sid, target, request_collections=scopes)
            ref = "pointer:" + uuid.uuid4().hex
            cx.execute("INSERT INTO resident_pointers VALUES(?,?,?,?,?,?,?,?,?)",
                       (ref,sid,target,p["purpose"],json.dumps(scopes),proposal["digest"],"approved",now,approval))
        else:
            private = set(scopes) - {"general"}
            if len(private) > 1:
                raise PermissionError("Material spanning multiple private collections must be split before approval")
            collection = next(iter(private), "general")
            if kind == "library":
                ref = "doc:" + uuid.uuid4().hex
                cx.execute("INSERT INTO library_documents VALUES(?,?,?,?,?,?,?,?,?)",
                           (ref,p["title"],p["text"],collection,evidence,proposal["digest"],"approved",now,approval))
            elif kind == "archive":
                # A research snapshot is labelled as derived research, never as an original user chat.
                raw = json.dumps(dict(type="approved_commons_material",markdown=p["text"],sources=snapshots), ensure_ascii=False)
                source_sha = proposal["digest"]
                cid = "research:" + proposal["id"]
                ref = "msg:" + source_sha[:32]
                cx.execute("INSERT INTO imports VALUES(?,?,?,?,?,?,NULL)",
                           (source_sha,"Commons approved research snapshot",len(raw.encode()),"complete",1,now))
                cx.execute("INSERT INTO conversations VALUES(?,?,?,?,?)", (cid,p["title"],str(now),raw,source_sha))
                cx.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (ref,cid,proposal["id"],"","research",str(now),p["text"],raw,1,collection))
                rowid = cx.execute("SELECT rowid FROM messages WHERE citation=?", (ref,)).fetchone()[0]
                cx.execute("INSERT INTO message_fts(rowid,text,title) VALUES(?,?,?)", (rowid,p["text"],p["title"]))
            else:
                raise ValueError("Unknown approval kind")
        result = dict(reference=ref, kind=kind, digest=proposal["digest"])
        cx.execute("INSERT INTO commons_approvals VALUES(?,?,?)", (proposal["id"],proposal["digest"],json.dumps(result)))
        audit(cx,"commons_approve",ref,approval)
        return result


def withdraw(cx, reference, digest, approval):
    initialize(cx)
    table = {"doc": "library_documents", "memory": "resident_memories", "pointer": "resident_pointers"}.get(reference.split(":")[0])
    if not table or not approval:
        raise ValueError("Select an approved document, memory or pointer")
    with cx:
        row = cx.execute(f"SELECT digest FROM {table} WHERE id=? AND state='approved'", (reference,)).fetchone()
        if not row or row[0] != digest:
            raise ValueError("Review the current digest first")
        cx.execute(f"UPDATE {table} SET state='withdrawn' WHERE id=?", (reference,))
        audit(cx,"memory_withdraw",reference,approval)
    return dict(reference=reference,state="withdrawn")


def correct(cx,reference,digest,claim,purpose,approval):
    from village_infrastructure import bounded
    import hashlib
    bounded(claim,1600,'corrected memory');bounded(purpose,600,'applicability')
    initialize(cx)
    with cx:
        cx.execute('BEGIN IMMEDIATE')
        old=cx.execute("SELECT * FROM resident_memories WHERE id=? AND state='approved'",(reference,)).fetchone()
        if not old or old['digest']!=digest:raise ValueError('Review the exact current memory first')
        changed=dict(old);changed.update(claim=claim,applicability=purpose,approval=approval)
        changed['digest']=hashlib.sha256(json.dumps(changed,sort_keys=True).encode()).hexdigest()
        cx.execute('UPDATE resident_memories SET claim=?,applicability=?,digest=?,approval=? WHERE id=?',
                   (claim,purpose,changed['digest'],approval,reference))
        rev=cx.execute('SELECT coalesce(max(revision),0)+1 FROM resident_memory_revisions WHERE reference=?',(reference,)).fetchone()[0]
        cx.execute('INSERT INTO resident_memory_revisions VALUES(?,?,?)',(reference,rev,json.dumps(changed)))
        audit(cx,'owner_memory_correction',reference,approval)
    return dict(reference=reference,digest=changed['digest'],revision=rev)


def delete(cx,reference,digest,approval):
    initialize(cx)
    table={'doc':'library_documents','memory':'resident_memories','pointer':'resident_pointers'}.get(reference.split(':')[0])
    if not table:raise ValueError('Select a document, memory or pointer')
    with cx:
        cx.execute('BEGIN IMMEDIATE')
        row=cx.execute(f'SELECT digest FROM {table} WHERE id=?',(reference,)).fetchone()
        if not row or row[0]!=digest:raise ValueError('Review the current digest first')
        cx.execute(f'DELETE FROM {table} WHERE id=?',(reference,))
        if table=='resident_memories':cx.execute('DELETE FROM resident_memory_revisions WHERE reference=?',(reference,))
        audit(cx,'owner_memory_delete',reference,approval)
    return dict(reference=reference,state='deleted',note='Existing session copies and backups are not erased; quarantine expires separately.')
