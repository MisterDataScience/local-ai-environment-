"""Explicit, local Agent Village operations. No daemon, timers or model calls.

The operational database is local, never on a synchronised vault volume. The
owner must verify FileVault before private data may be imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import uuid

ROLES = ("researcher", "analyst", "coder", "writer", "reviewer")
ID = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
MAX_SOURCE = 4 * 1024**3
MAX_RECORD = 16 * 1024**2
SCHEMA = 1


def digest(data):
    return hashlib.sha256(data).hexdigest()


def secure_root(root, *, test_encrypted=False):
    root = Path(root).expanduser()
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError("Village path contains a symbolic link")
    if not test_encrypted:
        if sys.platform != "darwin":
            raise RuntimeError("Private Village storage requires a FileVault protected Mac")
        check = subprocess.run(["/usr/bin/fdesetup", "status"], capture_output=True, text=True, timeout=10)
        if check.returncode or "FileVault is On." not in check.stdout:
            raise RuntimeError("FileVault must be enabled before using private Village storage")
        if any(part in str(root).lower() for part in ("icloud", "mobile documents", "cryptomator")):
            raise ValueError("The live SQLite database cannot be placed in a synchronised vault")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_mode & 0o077:
        raise PermissionError("Village directory must be accessible only to its owner")
    root.chmod(0o700)
    for name in ("archive", "jobs", "exports"):
        path = root / name
        path.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise PermissionError("Insecure Village directory: " + name)
    return root


def connect(root, *, test_encrypted=False):
    root = secure_root(root, test_encrypted=test_encrypted)
    db = root / "village.sqlite"
    if db.is_symlink():
        raise ValueError("Database symlink rejected")
    if db.exists() and db.stat().st_mode & 0o077:
        raise PermissionError("Insecure Village database permissions")
    cx = sqlite3.connect(db, timeout=30)
    db.chmod(0o600)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys=ON")
    cx.execute("PRAGMA journal_mode=WAL")
    cx.executescript("""
        CREATE TABLE IF NOT EXISTS migration(version INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS imports(
            sha TEXT PRIMARY KEY, filename TEXT NOT NULL, size INTEGER NOT NULL,
            state TEXT NOT NULL, next_record INTEGER NOT NULL DEFAULT 0,
            created INTEGER NOT NULL, error TEXT);
        CREATE TABLE IF NOT EXISTS conversations(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT,
            raw_json TEXT NOT NULL, source_sha TEXT NOT NULL REFERENCES imports(sha));
        CREATE TABLE IF NOT EXISTS messages(
            citation TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
            message_id TEXT NOT NULL, parent_id TEXT, role TEXT NOT NULL, created TEXT,
            text TEXT NOT NULL, raw_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            collection TEXT NOT NULL DEFAULT 'private');
        CREATE INDEX IF NOT EXISTS message_current ON messages(conversation_id, message_id, active);
        CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(text, title, content='');
        CREATE TABLE IF NOT EXISTS collections(id TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS specialists(
            id TEXT PRIMARY KEY, parent_id TEXT REFERENCES specialists(id),
            role TEXT NOT NULL, status TEXT NOT NULL, tags TEXT NOT NULL,
            created INTEGER NOT NULL, approval TEXT);
        CREATE TABLE IF NOT EXISTS profiles(
            specialist_id TEXT NOT NULL REFERENCES specialists(id),
            revision INTEGER NOT NULL, instruction TEXT NOT NULL,
            created INTEGER NOT NULL, approval TEXT NOT NULL,
            PRIMARY KEY(specialist_id, revision));
        CREATE TABLE IF NOT EXISTS grants(
            specialist_id TEXT NOT NULL REFERENCES specialists(id),
            collection_id TEXT NOT NULL REFERENCES collections(id),
            PRIMARY KEY(specialist_id, collection_id));
        CREATE TABLE IF NOT EXISTS navigation(
            specialist_id TEXT NOT NULL REFERENCES specialists(id),
            collection_id TEXT NOT NULL REFERENCES collections(id),
            hint TEXT NOT NULL, PRIMARY KEY(specialist_id, collection_id));
        CREATE TABLE IF NOT EXISTS lessons(
            id TEXT NOT NULL, revision INTEGER NOT NULL, claim TEXT NOT NULL,
            kind TEXT NOT NULL, status TEXT NOT NULL, source_citation TEXT REFERENCES messages(citation),
            collection TEXT NOT NULL REFERENCES collections(id),
            specialist_id TEXT REFERENCES specialists(id), approval TEXT NOT NULL,
            created INTEGER NOT NULL, PRIMARY KEY(id, revision));
        CREATE TABLE IF NOT EXISTS proposals(
            id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
            created INTEGER NOT NULL, approval TEXT);
        CREATE TABLE IF NOT EXISTS audit(
            id TEXT PRIMARY KEY, operation TEXT NOT NULL, subject TEXT NOT NULL,
            at INTEGER NOT NULL, approval TEXT);
    """)
    version = cx.execute("SELECT max(version) FROM migration").fetchone()[0]
    if version not in (None, SCHEMA):
        cx.close()
        raise RuntimeError("Unknown Village schema version")
    if version is None:
        with cx:
            cx.execute("INSERT INTO migration VALUES (?)", (SCHEMA,))
            for collection in ("general", "private"):
                cx.execute("INSERT INTO collections(id) VALUES (?)", (collection,))
            for role in ROLES:
                sid = role + ".general"
                cx.execute("INSERT INTO specialists VALUES (?,?,?,?,?,?,?)",
                           (sid, None, role, "active", "[]", int(time.time()), "built-in"))
                cx.execute("INSERT INTO profiles VALUES (?,?,?,?,?)",
                           (sid, 1, "", int(time.time()), "built-in"))
                cx.execute("INSERT INTO grants VALUES (?,?)", (sid, "general"))
    return cx


def audit(cx, operation, subject, approval=None):
    cx.execute("INSERT INTO audit VALUES (?,?,?,?,?)",
               (uuid.uuid4().hex, operation, subject, int(time.time()), approval))


def objects(stream):
    """Decode a top-level JSON array one bounded object at a time."""
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    ended = False
    while True:
        block = stream.read(65536)
        buffer += block
        while True:
            buffer = buffer.lstrip()
            if not started:
                if not buffer:
                    break
                if buffer[0] != "[":
                    raise ValueError("Expected conversations.json array")
                buffer = buffer[1:]
                started = True
                continue
            if buffer.startswith("]"):
                ended = True
                buffer = buffer[1:]
                break
            if buffer.startswith(","):
                buffer = buffer[1:]
                continue
            if not buffer:
                break
            try:
                item, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                if len(buffer.encode("utf-8")) > MAX_RECORD:
                    raise ValueError("Conversation exceeds bounded decoder limit")
                break
            if not isinstance(item, dict):
                raise ValueError("Conversation entry must be an object")
            yield item
            buffer = buffer[end:]
        if ended:
            if buffer.strip() or stream.read(1):
                raise ValueError("Trailing data after conversations")
            return
        if not block:
            raise ValueError("Incomplete conversations.json")
        if len(buffer.encode("utf-8")) > MAX_RECORD:
            raise ValueError("Conversation exceeds bounded decoder limit")


def extract_text(content):
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts", [])
    if not isinstance(parts, list):
        return ""
    return "\n".join(p for p in parts if isinstance(p, str))


def import_file(cx, root, source, *, confirm=False, stop_after=None):
    source = Path(source)
    if not confirm:
        raise PermissionError("Import requires --confirm after reviewing source and destination")
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_SOURCE:
        raise ValueError("Source must be a regular, single-link file within the size limit")
    if source.name != "conversations.json":
        raise ValueError("Select the exported conversations.json file")
    h = hashlib.sha256()
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("Source changed while opening")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        after = os.fstat(stream.fileno())
        if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Source changed during hashing")
    sha = h.hexdigest()
    archive = root / "archive" / (sha + ".json")
    if not archive.exists():
        temporary = root / "archive" / (sha + "." + uuid.uuid4().hex + ".partial")
        try:
            in_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(in_fd, "rb") as inp, temporary.open("xb") as out:
                opened = os.fstat(inp.fileno())
                if (opened.st_dev, opened.st_ino, opened.st_mtime_ns, opened.st_ctime_ns) != (
                        info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns):
                    raise ValueError("Source changed during copy")
                os.chmod(temporary, 0o600)
                shutil.copyfileobj(inp, out, length=1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, archive)
        finally:
            temporary.unlink(missing_ok=True)
    archived = archive.lstat()
    if not stat.S_ISREG(archived.st_mode) or archived.st_nlink != 1 or archived.st_mode & 0o077:
        raise ValueError("Archived source permissions or type changed")
    check = hashlib.sha256()
    with archive.open("rb") as verify:
        for block in iter(lambda: verify.read(1024 * 1024), b""):
            check.update(block)
    if check.hexdigest() != sha:
        raise ValueError("Archived source differs from its receipt")
    receipt = cx.execute("SELECT * FROM imports WHERE sha=?", (sha,)).fetchone()
    if receipt and receipt["state"] == "complete":
        return {"sha": sha, "state": "already imported", "records": receipt["next_record"]}
    with cx:
        cx.execute("INSERT OR IGNORE INTO imports VALUES (?,?,?,?,?,?,?)",
                   (sha, source.name, info.st_size, "paused", 0, int(time.time()), None))
    offset = cx.execute("SELECT next_record FROM imports WHERE sha=?", (sha,)).fetchone()[0]
    count = 0
    try:
        with archive.open(encoding="utf-8") as stream:
            for position, conversation in enumerate(objects(stream)):
                if position < offset:
                    continue
                raw = json.dumps(conversation, ensure_ascii=False, separators=(",", ":"))
                cid = str(conversation.get("id") or "missing-" + digest(raw.encode())[:24])
                title = str(conversation.get("title") or "")[:1000]
                mapping = conversation.get("mapping") or {}
                if not isinstance(mapping, dict):
                    mapping = {}
                with cx:
                    cx.execute("""INSERT INTO conversations VALUES (?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET title=excluded.title, created=excluded.created,
                        raw_json=excluded.raw_json, source_sha=excluded.source_sha""",
                               (cid, title, str(conversation.get("create_time") or ""), raw, sha))
                    cx.execute("UPDATE messages SET active=0 WHERE conversation_id=?", (cid,))
                    seen = set()
                    for node_id, node in mapping.items():
                        if not isinstance(node, dict):
                            continue
                        msg = node.get("message")
                        if not isinstance(msg, dict):
                            continue
                        mid = str(msg.get("id") or node_id)
                        if mid in seen:
                            mid = str(node_id)
                        seen.add(mid)
                        body = extract_text(msg.get("content"))
                        raw_msg = json.dumps(node, ensure_ascii=False, separators=(",", ":"))
                        citation = "msg:" + digest((cid + "\0" + mid + "\0" + raw_msg).encode())[:32]
                        old = cx.execute("SELECT collection FROM messages WHERE conversation_id=? AND message_id=? ORDER BY rowid DESC LIMIT 1",
                                         (cid, mid)).fetchone()
                        collection = old[0] if old else "private"
                        cx.execute("""INSERT OR IGNORE INTO messages
                            (citation, conversation_id, message_id, parent_id, role, created, text, raw_json, active, collection)
                            VALUES (?,?,?,?,?,?,?,?,1,?)""",
                                   (citation, cid, mid, str(node.get("parent") or ""),
                                    str((msg.get("author") or {}).get("role") or "unknown"),
                                    str(msg.get("create_time") or ""), body, raw_msg, collection))
                        cx.execute("UPDATE messages SET active=1 WHERE citation=?", (citation,))
                        row = cx.execute("SELECT rowid FROM messages WHERE citation=?", (citation,)).fetchone()[0]
                        if not cx.execute("SELECT 1 FROM message_fts WHERE rowid=?", (row,)).fetchone():
                            cx.execute("INSERT INTO message_fts(rowid,text,title) VALUES (?,?,?)", (row, body, title))
                    cx.execute("UPDATE imports SET next_record=?, state='paused', error=NULL WHERE sha=?",
                               (position + 1, sha))
                count += 1
                if stop_after and count >= stop_after:
                    return {"sha": sha, "state": "paused", "records": position + 1}
        with cx:
            cx.execute("UPDATE imports SET state='complete' WHERE sha=?", (sha,))
            audit(cx, "import", sha)
        return {"sha": sha, "state": "complete", "records": offset + count}
    except Exception as exc:
        with cx:
            cx.execute("UPDATE imports SET state='error', error=? WHERE sha=?", (type(exc).__name__, sha))
        raise


def specialist(cx, sid):
    row = cx.execute("SELECT * FROM specialists WHERE id=? AND status='active'", (sid,)).fetchone()
    if not row:
        raise PermissionError("Specialist is unavailable")
    return row


def grants(cx, sid):
    row = cx.execute("SELECT parent_id FROM specialists WHERE id=?", (sid,)).fetchone()
    if not row:
        raise PermissionError("Specialist unavailable")
    own = {r[0] for r in cx.execute("SELECT collection_id FROM grants WHERE specialist_id=?", (sid,))}
    return own & grants(cx, row[0]) if row[0] else own


def search(cx, sid, query, *, request_collections=("general",), limit=5, role=None, title=None, owner=False):
    if not owner:
        specialist(cx, sid)
    allowed = set(request_collections) if owner else grants(cx, sid) & set(request_collections)
    if not allowed:
        return []
    if not isinstance(query, str) or not query.strip() or len(query) > 300:
        raise ValueError("Invalid search")
    limit = max(1, min(int(limit), 10))
    match = '"' + query.replace('"', '""') + '"'
    slots = ",".join("?" for _ in allowed)
    sql = ("""SELECT m.citation,m.role,m.created,m.collection,c.title,
                     substr(m.text,1,600) AS excerpt
              FROM message_fts f JOIN messages m ON m.rowid=f.rowid
              JOIN conversations c ON c.id=m.conversation_id
              WHERE message_fts MATCH ? AND m.active=1 AND m.collection IN (""" + slots + ")")
    params = [match, *sorted(allowed)]
    if role:
        sql += " AND m.role=?"
        params.append(role)
    if title:
        sql += " AND c.title LIKE ?"
        params.append("%" + title.replace("%", "\\%").replace("_", "\\_") + "%")
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    return [dict(row) for row in cx.execute(sql, params)]


def read(cx, sid, citation, *, request_collections=("general",), max_chars=2500, owner=False):
    if not owner:
        specialist(cx, sid)
    allowed = set(request_collections) if owner else grants(cx, sid) & set(request_collections)
    row = cx.execute("""SELECT m.citation,m.message_id,m.parent_id,m.role,m.created,
                        m.text,m.collection,c.title,c.id AS conversation_id
                        FROM messages m JOIN conversations c ON c.id=m.conversation_id
                        WHERE m.citation=? AND m.active=1""", (citation,)).fetchone()
    if not row or row["collection"] not in allowed:
        raise PermissionError("Passage unavailable")
    result = dict(row)
    result["text"] = result["text"][:max(1, min(int(max_chars), 4000))]
    return result


def status(cx):
    return [dict(row) for row in cx.execute("""SELECT s.id,s.parent_id,s.role,s.status,s.tags,
                       (SELECT max(revision) FROM profiles WHERE specialist_id=s.id) AS revision
                       FROM specialists s ORDER BY s.id""")]


def propose(cx, *, sid, parent, role, tags, instruction, collections):
    if not ID.fullmatch(sid) or role not in ROLES or not isinstance(tags, list) or not isinstance(collections, list):
        raise ValueError("Invalid specialist proposal")
    if len(instruction) > 1200 or any(not ID.fullmatch(t) for t in tags + collections):
        raise ValueError("Invalid proposal fields")
    base = specialist(cx, parent)
    if base["role"] != role or cx.execute("SELECT 1 FROM specialists WHERE id=?", (sid,)).fetchone():
        raise ValueError("Invalid parent role or duplicate specialist")
    if set(collections) - grants(cx, parent):
        raise PermissionError("Daughter cannot inherit ungranted collections")
    payload = dict(id=sid, parent=parent, role=role, tags=tags, instruction=instruction, collections=collections)
    pid = uuid.uuid4().hex
    with cx:
        cx.execute("INSERT INTO proposals VALUES (?,?,?,?,NULL)", (pid, json.dumps(payload), "pending", int(time.time())))
        audit(cx, "propose", pid)
    return {"proposal_id": pid, "payload": payload, "status": "pending"}


def approve(cx, proposal_id, approval):
    if not approval or len(approval) > 120 or not proposal_id:
        raise ValueError("Explicit owner approval reference required")
    row = cx.execute("SELECT * FROM proposals WHERE id=? AND state='pending'", (proposal_id,)).fetchone()
    if not row:
        raise ValueError("Proposal unavailable")
    p = json.loads(row["payload"])
    # Recheck grants and parent role at commit time, including revocation.
    base = specialist(cx, p["parent"])
    if base["role"] != p["role"] or set(p["collections"]) - grants(cx, p["parent"]):
        raise PermissionError("Parent or grants changed since proposal")
    with cx:
        cx.execute("INSERT INTO specialists VALUES (?,?,?,?,?,?,?)",
                   (p["id"], p["parent"], p["role"], "experimental", json.dumps(p["tags"]), int(time.time()), approval))
        cx.execute("INSERT INTO profiles VALUES (?,?,?,?,?)", (p["id"], 1, p["instruction"], int(time.time()), approval))
        for collection in p["collections"]:
            cx.execute("INSERT INTO grants VALUES (?,?)", (p["id"], collection))
        cx.execute("UPDATE proposals SET state='approved', approval=? WHERE id=?", (approval, proposal_id))
        audit(cx, "approve", p["id"], approval)
    return p["id"]


def activate(cx, sid, approval):
    if not approval:
        raise ValueError("Explicit owner approval reference required")
    row = cx.execute("SELECT * FROM specialists WHERE id=?", (sid,)).fetchone()
    if not row or row["parent_id"] is None:
        raise ValueError("Only approved daughters may change lifecycle")
    if row["parent_id"]:
        specialist(cx, row["parent_id"])
        raw = {r[0] for r in cx.execute("SELECT collection_id FROM grants WHERE specialist_id=?", (sid,))}
        if raw - grants(cx, row["parent_id"]):
            raise PermissionError("Parent grants revoked")
    with cx:
        cx.execute("UPDATE specialists SET status='active' WHERE id=?", (sid,))
        audit(cx, "activate", sid, approval)


def route(cx, role, objective, *, request_collections=("general",)):
    if role not in ROLES:
        raise ValueError("Unknown permission template")
    words = set(re.findall(r"[a-z0-9]+", objective.lower()))
    candidates = []
    for row in cx.execute("SELECT id,tags FROM specialists WHERE role=? AND status='active' AND parent_id IS NOT NULL", (role,)):
        if not grants(cx, row["id"]) or grants(cx, row["id"]) - set(request_collections):
            continue
        score = len(words & set(json.loads(row["tags"])))
        if score:
            candidates.append((score, row["id"]))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1] if candidates else role + ".general"


def packet(cx, sid, *, request_collections=("general",), objective=""):
    row = specialist(cx, sid)
    if not grants(cx, sid) or grants(cx, sid) - set(request_collections):
        raise PermissionError("Specialist scope exceeds the current request")
    profile = cx.execute("SELECT * FROM profiles WHERE specialist_id=? ORDER BY revision DESC LIMIT 1", (sid,)).fetchone()
    # A short packet is deliberately not an archive dump.
    allowed = grants(cx, sid) & set(request_collections)
    slots = ",".join("?" for _ in allowed)
    lessons = [dict(r) for r in cx.execute("""SELECT l.id,l.claim,l.source_citation FROM lessons l
        JOIN messages m ON m.citation=l.source_citation AND m.active=1
        WHERE l.specialist_id IN (?,?) AND l.status='approved' AND l.collection IN (""" + slots + """)
        AND l.revision=(SELECT max(x.revision) FROM lessons x WHERE x.id=l.id)
        ORDER BY l.created DESC LIMIT 3""", (sid, row["parent_id"] or sid, *sorted(allowed)))]
    return dict(id=sid, role=row["role"], revision=profile["revision"],
                instruction=profile["instruction"][:1000], lessons=lessons,
                allowed_collections=sorted(grants(cx, sid)))


def add_lesson(cx, *, claim, kind, citation, specialist_id, approval):
    if not approval or not claim or len(claim) > 500 or kind not in (
            "observed_outcome", "verified_procedure", "explicit_preference",
            "inferred_preference", "project_fact", "correction", "counterexample"):
        raise ValueError("Invalid lesson or missing owner approval")
    source = cx.execute("SELECT collection,role FROM messages WHERE citation=? AND active=1", (citation,)).fetchone()
    if not source or source["collection"] not in grants(cx, specialist_id):
        raise PermissionError("Source evidence unavailable")
    if kind == "explicit_preference" and source["role"] != "user":
        raise ValueError("Explicit preferences require a user-authored source")
    lid = uuid.uuid4().hex
    with cx:
        cx.execute("INSERT INTO lessons VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (lid, 1, claim, kind, "approved", citation, source["collection"],
                    specialist_id, approval, int(time.time())))
        audit(cx, "lesson", lid, approval)
    return {"id": lid, "revision": 1, "source": citation}


def revise_lesson(cx, lid, *, claim, status, approval):
    if not approval or status not in ("approved", "superseded", "retracted") or len(claim) > 500:
        raise ValueError("Invalid revision")
    old = cx.execute("SELECT * FROM lessons WHERE id=? ORDER BY revision DESC LIMIT 1", (lid,)).fetchone()
    if not old:
        raise ValueError("Lesson unavailable")
    with cx:
        cx.execute("INSERT INTO lessons VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (lid, old["revision"] + 1, claim, old["kind"], status, old["source_citation"],
                    old["collection"], old["specialist_id"], approval, int(time.time())))
        audit(cx, "revise_lesson", lid, approval)
    return {"id": lid, "revision": old["revision"] + 1, "status": status}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Owner operated Agent Village, no background jobs")
    parser.add_argument("--root", type=Path, default=Path.home() / "LocalAI-Automated/village")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import")
    imp.add_argument("source", type=Path)
    imp.add_argument("--confirm", action="store_true")
    query = commands.add_parser("search")
    query.add_argument("specialist")
    query.add_argument("query")
    query.add_argument("--collection", action="append", default=["general"])
    lookup = commands.add_parser("read")
    lookup.add_argument("specialist")
    lookup.add_argument("citation")
    lookup.add_argument("--collection", action="append", default=["general"])
    commands.add_parser("status")
    prop = commands.add_parser("propose")
    prop.add_argument("id"); prop.add_argument("parent"); prop.add_argument("role")
    prop.add_argument("--tag", action="append", default=[])
    prop.add_argument("--collection", action="append", default=["general"])
    prop.add_argument("--instruction", default="")
    appr = commands.add_parser("approve")
    appr.add_argument("proposal_id"); appr.add_argument("--owner-approval", required=True)
    act = commands.add_parser("activate")
    act.add_argument("id"); act.add_argument("--owner-approval", required=True)
    grant = commands.add_parser("grant")
    grant.add_argument("id"); grant.add_argument("collection")
    grant.add_argument("--owner-approval", required=True)
    classify = commands.add_parser("classify")
    classify.add_argument("conversation_id"); classify.add_argument("collection")
    classify.add_argument("--owner-approval", required=True)
    lesson = commands.add_parser("lesson")
    lesson.add_argument("specialist"); lesson.add_argument("citation"); lesson.add_argument("kind"); lesson.add_argument("claim")
    lesson.add_argument("--owner-approval", required=True)
    revise = commands.add_parser("revise-lesson")
    revise.add_argument("id"); revise.add_argument("status"); revise.add_argument("claim")
    revise.add_argument("--owner-approval", required=True)
    for name in ("host-route", "host-packet", "host-search", "host-read"):
        host = commands.add_parser(name)
        host.add_argument("specialist_or_role")
        host.add_argument("value")
    args = parser.parse_args(argv)
    cx = connect(args.root)
    try:
        if args.command == "import":
            print(json.dumps({"source": str(args.source), "bytes": args.source.stat().st_size,
                              "destination": str(args.root), "confirmed": args.confirm}))
            result = import_file(cx, args.root, args.source, confirm=args.confirm)
        elif args.command == "search":
            result = search(cx, args.specialist, args.query, request_collections=args.collection, owner=True)
        elif args.command == "read":
            result = read(cx, args.specialist, args.citation, request_collections=args.collection, owner=True)
        elif args.command == "status":
            result = status(cx)
        elif args.command == "propose":
            result = propose(cx, sid=args.id, parent=args.parent, role=args.role,
                             tags=args.tag, instruction=args.instruction, collections=args.collection)
        elif args.command == "approve":
            result = approve(cx, args.proposal_id, args.owner_approval)
        elif args.command == "activate":
            result = activate(cx, args.id, args.owner_approval)
        elif args.command == "grant":
            specialist(cx, args.id)
            if not cx.execute("SELECT 1 FROM collections WHERE id=?", (args.collection,)).fetchone():
                raise ValueError("Unknown collection")
            with cx:
                cx.execute("INSERT OR IGNORE INTO grants VALUES (?,?)", (args.id, args.collection))
                audit(cx, "grant", args.id + ":" + args.collection, args.owner_approval)
            result = {"granted": args.collection}
        elif args.command == "classify":
            if not cx.execute("SELECT 1 FROM collections WHERE id=?", (args.collection,)).fetchone():
                raise ValueError("Unknown collection")
            with cx:
                cx.execute("UPDATE messages SET collection=? WHERE conversation_id=?",
                           (args.collection, args.conversation_id))
                if not cx.execute("SELECT changes()").fetchone()[0]:
                    raise ValueError("Conversation unavailable")
                audit(cx, "classify", args.conversation_id, args.owner_approval)
            result = {"conversation": args.conversation_id, "collection": args.collection}
        elif args.command == "lesson":
            result = add_lesson(cx, claim=args.claim, kind=args.kind, citation=args.citation,
                                specialist_id=args.specialist, approval=args.owner_approval)
        elif args.command == "revise-lesson":
            result = revise_lesson(cx, args.id, claim=args.claim, status=args.status, approval=args.owner_approval)
        elif args.command == "host-route":
            result = route(cx, args.specialist_or_role, args.value)
        elif args.command == "host-packet":
            result = packet(cx, args.specialist_or_role)
        elif args.command == "host-search":
            result = search(cx, args.specialist_or_role, args.value)
        else:
            result = read(cx, args.specialist_or_role, args.value)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        cx.close()


if __name__ == "__main__":
    main()
