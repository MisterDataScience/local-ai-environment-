"""Shared Village facilities. Local records only; never execute contributed code.

Host calls carry a project and identity supplied by Captain, not model arguments.
Approval and lifecycle operations are owner CLI operations, never host tools.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from village import audit, grants, specialist

AREAS = ("workshop", "noticeboard", "suggestions", "practice")
KINDS = ("python", "shell", "template", "checklist", "text")
HEX = re.compile(r"^[a-f0-9]{64}$")
FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
MAX_CONTENT = 16000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bounded(value, limit, label, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or "\0" in value:
        raise ValueError("Invalid " + label)
    return value


def project_key(path):
    return sha(str(Path(path).expanduser().resolve(strict=True)))


def initialize(cx):
    """Independent additive migration; never change existing Village identities."""
    version = cx.execute("SELECT name FROM sqlite_master WHERE name='facility_schema'").fetchone()
    if version:
        versions = [r[0] for r in cx.execute("SELECT version FROM facility_schema")]
        if versions != [1]:
            raise RuntimeError("Unknown Village facilities schema")
        return
    with cx:
        # Start before DDL so interruption cannot leave a partial version marker.
        cx.execute("BEGIN IMMEDIATE")
        statements = [
            "CREATE TABLE IF NOT EXISTS facility_schema(version INTEGER PRIMARY KEY)",
            "INSERT OR IGNORE INTO facility_schema VALUES(1)",
            """CREATE TABLE IF NOT EXISTS workshop_items(
                id TEXT PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL,
                kind TEXT NOT NULL, author TEXT NOT NULL, active_revision INTEGER,
                created INTEGER NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS workshop_revisions(
                item_id TEXT NOT NULL REFERENCES workshop_items(id), revision INTEGER NOT NULL,
                purpose TEXT NOT NULL, content TEXT NOT NULL, evidence TEXT NOT NULL,
                tags TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL,
                approval TEXT, reviewed INTEGER, author TEXT NOT NULL, PRIMARY KEY(item_id,revision))""",
            """CREATE TABLE IF NOT EXISTS facility_entries(
                id TEXT PRIMARY KEY, area TEXT NOT NULL, project TEXT NOT NULL,
                author TEXT NOT NULL, task TEXT NOT NULL, title TEXT NOT NULL,
                body TEXT NOT NULL, evidence TEXT NOT NULL, state TEXT NOT NULL,
                digest TEXT NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL,
                approval TEXT)""",
            "CREATE INDEX IF NOT EXISTS facility_project ON facility_entries(project,area,updated)",
            """CREATE TABLE IF NOT EXISTS practice_cases(
                id TEXT PRIMARY KEY, project TEXT NOT NULL, author TEXT NOT NULL,
                item_id TEXT NOT NULL, revision INTEGER NOT NULL, artifact_digest TEXT NOT NULL,
                brief TEXT NOT NULL, checks TEXT NOT NULL, fixtures TEXT NOT NULL,
                digest TEXT NOT NULL, workspace TEXT NOT NULL, created INTEGER NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS practice_results(
                entry_id TEXT PRIMARY KEY REFERENCES facility_entries(id),
                case_id TEXT NOT NULL REFERENCES practice_cases(id))""",
            """CREATE TABLE IF NOT EXISTS practice_projects(
                case_id TEXT NOT NULL REFERENCES practice_cases(id), project TEXT NOT NULL,
                PRIMARY KEY(case_id,project))""",
            """CREATE TABLE IF NOT EXISTS facility_receipts(
                request_id TEXT PRIMARY KEY, digest TEXT NOT NULL, response TEXT NOT NULL)""",
        ]
        for statement in statements:
            cx.execute(statement)


def evidence(cx, values):
    if not isinstance(values, list) or len(values) > 8:
        raise ValueError("Provide at most eight evidence references")
    for value in values:
        bounded(value, 500, "evidence reference")
        if value.startswith("msg:"):
            row = cx.execute("SELECT active,collection FROM messages WHERE citation=?", (value,)).fetchone()
            if not row or not row["active"] or row["collection"] != "general":
                raise PermissionError("Only current general archive citations may be shared")
    return values


def workshop_read(cx, item_id, project, *, owner=False):
    row = cx.execute("""SELECT i.*,r.revision,r.purpose,r.content,r.evidence,r.tags,r.digest,
        r.state,r.approval,r.reviewed,r.author AS revision_author FROM workshop_items i JOIN workshop_revisions r
        ON r.item_id=i.id AND r.revision=i.active_revision WHERE i.id=? AND r.state='approved'""",
        (item_id,)).fetchone()
    if not row:
        raise PermissionError("No approved workshop revision is available")
    result = dict(row)
    result.update(executable=False, evidence_status="owner reviewed; checks are reported evidence",
                  evidence=json.loads(result["evidence"]), tags=json.loads(result["tags"]))
    return result


def case_access(cx, case_id, project):
    return cx.execute("""SELECT c.* FROM practice_cases c WHERE c.id=? AND
        (c.project=? OR EXISTS(SELECT 1 FROM practice_projects p WHERE p.case_id=c.id AND p.project=?))""",
        (case_id, project, project)).fetchone()


def browse(cx, area, project, *, query="", item_id="", owner=False):
    if area not in AREAS:
        raise ValueError("Unknown facility")
    bounded(query, 200, "query", empty=True)
    bounded(item_id, 80, "item ID", empty=True)
    if item_id:
        if area == "workshop":
            if owner:
                rows = cx.execute("""SELECT i.*,r.*,r.author AS revision_author FROM workshop_items i JOIN workshop_revisions r
                    ON r.item_id=i.id WHERE i.id=? ORDER BY r.revision DESC LIMIT 20""", (item_id,)).fetchall()
                return [dict(r) for r in rows]
            return workshop_read(cx, item_id, project)
        table = "practice_cases" if area == "practice" else "facility_entries"
        row = case_access(cx, item_id, project) if area == "practice" else cx.execute(f"SELECT * FROM {table} WHERE id=? AND project=?" +
                         (" AND area=?" if table == "facility_entries" else ""),
                         (item_id, project, area) if table == "facility_entries" else (item_id, project)).fetchone()
        if not row:
            raise PermissionError("Record is unavailable in this project")
        result = dict(row)
        if area == "practice":
            result["results"] = [dict(r) for r in cx.execute("""SELECT e.id,e.author,e.body,e.evidence,
                e.state,e.digest,e.approval FROM facility_entries e JOIN practice_results p ON p.entry_id=e.id
                WHERE p.case_id=? ORDER BY e.created DESC,e.id LIMIT 10""", (item_id,))]
        return result
    # Parameterized LIKE with literal escaping; only compact cards leave the DB.
    match = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if area == "workshop":
        sql = """SELECT i.id,i.title,i.kind,i.author,r.revision,r.purpose,r.digest,r.state,r.reviewed
            FROM workshop_items i JOIN workshop_revisions r ON r.item_id=i.id
            WHERE (r.revision=i.active_revision AND r.state='approved'"""
        sql += " OR i.project=?" if owner else ""
        sql += ") AND (i.title LIKE ? ESCAPE '\\' OR r.purpose LIKE ? ESCAPE '\\') ORDER BY i.created DESC,i.id LIMIT 10"
        return [dict(r) for r in cx.execute(sql, (project, match, match) if owner else (match, match))]
    if area == "practice":
        return [dict(r) for r in cx.execute("""SELECT c.id,c.item_id,c.revision,c.brief,c.digest,c.workspace,c.created
            FROM practice_cases c WHERE (c.project=? OR EXISTS(SELECT 1 FROM practice_projects p
            WHERE p.case_id=c.id AND p.project=?)) AND c.brief LIKE ? ESCAPE '\\' ORDER BY c.created DESC,c.id LIMIT 10""",
            (project, project, match))]
    return [dict(r) for r in cx.execute("""SELECT id,author,task,title,substr(body,1,500) AS excerpt,
        state,digest,updated FROM facility_entries WHERE project=? AND area=?
        AND (title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\') ORDER BY updated DESC,id LIMIT 10""",
        (project, area, match, match))]


def publish(cx, project, actor, task, payload, *, owner=False):
    allowed = {"area", "title", "body", "content", "kind", "tags", "evidence", "item_id", "state"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError("Unknown contribution fields")
    area = payload.get("area")
    if area not in ("workshop", "noticeboard", "suggestions", "practice"):
        raise ValueError("Unknown contribution area")
    title = bounded(payload.get("title"), 120, "title")
    body = bounded(payload.get("body"), 1600, "description")
    refs = evidence(cx, payload.get("evidence", []))
    now = int(time.time())
    if cx.execute("SELECT count(*) FROM facility_entries WHERE project=?", (project,)).fetchone()[0] >= 20000:
        raise ValueError("Project record limit reached; review stored contributions before adding more")
    if area == "workshop":
        kind = payload.get("kind", "text")
        content = bounded(payload.get("content"), MAX_CONTENT, "artifact content")
        tags = payload.get("tags", [])
        if kind not in KINDS or not isinstance(tags, list) or len(tags) > 12:
            raise ValueError("Invalid artifact kind or tags")
        for tag in tags:
            bounded(tag, 40, "tag")
        item_id = payload.get("item_id") or "tool:" + uuid.uuid4().hex
        old = cx.execute("SELECT * FROM workshop_items WHERE id=?", (item_id,)).fetchone()
        if not old and cx.execute("SELECT count(*) FROM workshop_items").fetchone()[0] >= 10000:
            raise ValueError("Workshop item limit reached")
        if payload.get("item_id") and not old:
            raise ValueError("Workshop item does not exist")
        if old and (old["project"] != project or (old["author"] != actor and not owner) or old["kind"] != kind or old["title"] != title):
            raise PermissionError("Only the original project and author may propose a revision; keep its title and kind")
        revision = cx.execute("SELECT coalesce(max(revision),0)+1 FROM workshop_revisions WHERE item_id=?", (item_id,)).fetchone()[0]
        content_digest = sha(encoded(dict(title=title, kind=kind, purpose=body, content=content, evidence=refs, tags=tags)))
        cx.execute("INSERT OR IGNORE INTO workshop_items VALUES(?,?,?,?,?,NULL,?)",
                   (item_id, project, title, kind, actor, now))
        cx.execute("INSERT INTO workshop_revisions VALUES(?,?,?,?,?,?,?,?,NULL,NULL,?)",
                   (item_id, revision, body, content, encoded(refs), encoded(tags), content_digest, "pending", actor))
        audit(cx, "workshop_propose", item_id + ":" + str(revision))
        return dict(id=item_id, revision=revision, digest=content_digest, state="pending", executable=False)
    if payload.get("content") or payload.get("tags") or payload.get("kind"):
        raise ValueError("Content, tags and kind belong only to workshop contributions")
    item_id = "entry:" + uuid.uuid4().hex
    state = payload.get("state", "open" if area == "noticeboard" else "proposed")
    if area == "practice":
        case_id = bounded(payload.get("item_id"), 80, "practice case")
        case = case_access(cx, case_id, project)
        if not case or state not in ("reported_pass", "reported_fail", "inconclusive"):
            raise ValueError("Use a project practice case and a reported result state")
        body = "Case " + case_id + "; fixture digest " + case["digest"] + "\n" + body
    elif payload.get("item_id"):
        raise ValueError("A contribution cannot overwrite another entry")
    elif state != ("open" if area == "noticeboard" else "proposed"):
        raise ValueError("Lifecycle decisions require the owner command")
    content_digest = sha(encoded(dict(area=area, title=title, body=body, evidence=refs, state=state)))
    cx.execute("INSERT INTO facility_entries VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
               (item_id, area, project, actor, task, title, body, encoded(refs), state, content_digest, now, now))
    if area == "practice":
        cx.execute("INSERT INTO practice_results VALUES(?,?)", (item_id, case_id))
    audit(cx, "facility_contribute", item_id)
    return dict(id=item_id, digest=content_digest, state=state, evidence_status="reported, not independently verified")


def owner_decision(cx, area, item_id, decision, expected, approval, *, revision=None, project=None):
    bounded(approval, 120, "owner approval")
    if not HEX.fullmatch(expected):
        raise ValueError("Supply the exact reviewed digest")
    with cx:
        cx.execute("BEGIN IMMEDIATE")
        if area == "workshop":
            if decision not in ("approved", "rejected", "withdrawn"):
                raise ValueError("Invalid workshop decision")
            row = cx.execute("SELECT * FROM workshop_revisions WHERE item_id=? AND revision=?", (item_id, revision)).fetchone()
            latest = cx.execute("SELECT max(revision) FROM workshop_revisions WHERE item_id=?", (item_id,)).fetchone()[0]
            if not row or row["digest"] != expected or (decision != "withdrawn" and latest != revision):
                raise ValueError("Revision or digest changed; review it again")
            if decision in ("approved", "rejected") and row["state"] != "pending":
                raise ValueError("Only pending revisions may be approved or rejected")
            if decision == "withdrawn" and row["state"] != "approved":
                raise ValueError("Only approved revisions may be withdrawn")
            cx.execute("UPDATE workshop_revisions SET state=?,approval=?,reviewed=? WHERE item_id=? AND revision=?",
                       (decision, approval, int(time.time()), item_id, revision))
            if decision == "approved":
                cx.execute("UPDATE workshop_revisions SET state='superseded' WHERE item_id=? AND state='approved' AND revision<>?", (item_id, revision))
                cx.execute("UPDATE workshop_items SET active_revision=? WHERE id=?", (revision, item_id))
            elif decision == "withdrawn":
                cx.execute("UPDATE workshop_items SET active_revision=NULL WHERE id=? AND active_revision=?", (item_id, revision))
        else:
            permitted = {"noticeboard": {"closed"}, "suggestions": {"accepted", "declined", "implemented"},
                         "practice": {"owner_accepted", "owner_rejected"}}
            if decision not in permitted.get(area, set()):
                raise ValueError("Invalid facility decision")
            row = cx.execute("SELECT * FROM facility_entries WHERE id=? AND area=? AND project=?", (item_id, area, project)).fetchone()
            if not row or row["digest"] != expected:
                raise ValueError("Entry or digest changed; review it again")
            transitions = {"open": {"closed"}, "proposed": {"accepted", "declined"},
                           "accepted": {"implemented", "declined"},
                           "reported_pass": {"owner_accepted", "owner_rejected"},
                           "reported_fail": {"owner_accepted", "owner_rejected"},
                           "inconclusive": {"owner_accepted", "owner_rejected"}}
            if decision not in transitions.get(row["state"], set()):
                raise ValueError("Lifecycle transition is unavailable")
            cx.execute("UPDATE facility_entries SET state=?,approval=?,updated=?,digest=? WHERE id=?",
                       (decision, approval, int(time.time()), sha(expected + "\0" + decision), item_id))
        audit(cx, "facility_owner_decision", item_id + ":" + decision, approval)
    return dict(id=item_id, state=decision)


def prepare(cx, root, project, actor, payload):
    if set(payload) - {"item_id", "brief", "checks", "fixtures"}:
        raise ValueError("Unknown practice fields")
    item = workshop_read(cx, payload.get("item_id"), project)
    brief = bounded(payload.get("brief"), 1600, "practice brief")
    checks = bounded(payload.get("checks"), 1600, "expected checks")
    fixtures = payload.get("fixtures", {})
    if not isinstance(fixtures, dict) or len(fixtures) > 12:
        raise ValueError("Provide at most twelve small text fixtures")
    for name, content in fixtures.items():
        if not FILE.fullmatch(name) or name in (".", ".."):
            raise ValueError("Fixture names must be simple filenames")
        bounded(content, MAX_CONTENT, "fixture", empty=True)
    if len(encoded(fixtures).encode()) > MAX_CONTENT:
        raise ValueError("Practice fixtures exceed 16 KB")
    pid = "case:" + uuid.uuid4().hex
    parent = Path(root) / "practice"
    if parent.is_symlink():
        raise ValueError("Practice directory symlink rejected")
    parent.mkdir(mode=0o700, exist_ok=True)
    if not parent.is_dir() or parent.stat().st_mode & 0o077:
        raise PermissionError("Practice directory must be private")
    workspace = parent / pid.replace(":", "-")
    workspace.mkdir(mode=0o700)
    (workspace / "inputs").mkdir(mode=0o700)
    manifest = dict(id=pid, project=project, item_id=item["id"], revision=item["revision"],
                    artifact_digest=item["digest"], brief=brief, checks=checks,
                    fixtures={name: sha(value) for name, value in fixtures.items()}, candidate_sha256=sha(item["content"]))
    checksum = sha(encoded(manifest))
    files = {"candidate.txt": item["content"], "manifest.json": encoded(manifest) + "\n",
             "README.md": "# Village practice case\n\n" + brief + "\n\nExpected checks:\n" + checks +
             "\n\nStart with Plan in a copied project. candidate.txt is inert text. This folder is not an OS sandbox. "
             "Build execution still needs native command approval. Record actual results separately.\n"}
    files.update({"inputs/" + name: value for name, value in fixtures.items()})
    for name, content in files.items():
        fd = os.open(workspace / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
    cx.execute("INSERT INTO practice_cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (pid, project, actor, item["id"], item["revision"], item["digest"], brief, checks,
                encoded(manifest["fixtures"]), checksum, str(workspace), int(time.time())))
    cx.execute("INSERT INTO practice_projects VALUES(?,?)", (pid, project_key(workspace)))
    audit(cx, "practice_prepare", pid)
    return dict(id=pid, workspace=str(workspace), digest=checksum, revision=item["revision"],
                artifact_digest=item["digest"], executed=False, instruction="Open a copy as a Work Agent project; review in Plan first.")


def validate_identity(cx, envelope):
    sid = envelope["identity"]
    specialist(cx, sid)
    cursor, visited = sid, set()
    while cursor:
        if cursor in visited:
            raise PermissionError("Specialist lineage cycle")
        visited.add(cursor)
        ancestor = specialist(cx, cursor)
        cursor = ancestor["parent_id"]
    current = cx.execute("SELECT max(revision) FROM profiles WHERE specialist_id=?", (sid,)).fetchone()[0]
    if current != envelope["revision"] or "general" not in grants(cx, sid):
        raise PermissionError("Specialist revision or scope changed")


def host(cx, root, envelope):
    initialize(cx)
    if not isinstance(envelope, dict) or set(envelope) != {"operation", "project", "identity", "revision", "actor", "task", "request_id", "payload"}:
        raise ValueError("Invalid host request")
    validate_identity(cx, envelope)
    sid = envelope["identity"]
    project = envelope["project"]
    if not isinstance(project, str) or not HEX.fullmatch(project):
        raise ValueError("Invalid project identity")
    actor = envelope["actor"]
    if actor not in (sid, "captain"):
        raise PermissionError("Invalid attribution")
    bounded(envelope["task"], 120, "task", empty=True)
    payload, operation = envelope["payload"], envelope["operation"]
    if not isinstance(payload, dict):
        raise ValueError("Invalid payload")
    if operation == "browse":
        if set(payload) - {"area", "query", "item_id"}:
            raise ValueError("Unknown browse fields")
        return browse(cx, project=project, **payload)
    request_id = bounded(envelope["request_id"], 64, "request ID")
    request_digest = sha(encoded(envelope))
    # Serialize mutations and reserve a durable receipt in the same transaction.
    cx.execute("BEGIN IMMEDIATE")
    try:
        # Recheck under the write lock: a concurrent revocation must win before
        # any contribution can commit with obsolete privileges.
        validate_identity(cx, envelope)
        old = cx.execute("SELECT * FROM facility_receipts WHERE request_id=?", (request_id,)).fetchone()
        if old:
            if old["digest"] != request_digest:
                raise ValueError("Replay request content changed")
            cx.rollback()
            return json.loads(old["response"])
        if operation == "publish":
            result = publish(cx, project, actor, envelope["task"], payload)
        elif operation == "prepare" and actor == "captain":
            result = prepare(cx, root, project, actor, payload)
        else:
            raise PermissionError("Operation is unavailable to host tools")
        cx.execute("INSERT INTO facility_receipts VALUES(?,?,?)", (request_id, request_digest, encoded(result)))
        cx.commit()
        return result
    except Exception:
        cx.rollback()
        raise


def register_commands(commands):
    for area in AREAS:
        parser = commands.add_parser(area, help="Explicit Village " + area + " operations")
        parser.add_argument("--project", type=Path, required=True, help="The active Work Agent project folder")
        actions = parser.add_subparsers(dest="action", required=True)
        listing = actions.add_parser("list")
        listing.add_argument("--query", default="")
        show = actions.add_parser("show")
        show.add_argument("id")
        if area == "workshop":
            proposal = actions.add_parser("propose")
            proposal.add_argument("title"); proposal.add_argument("--kind", choices=KINDS, default="text")
            proposal.add_argument("--purpose", required=True); proposal.add_argument("--file", type=Path, required=True)
            proposal.add_argument("--evidence", action="append", default=[])
            proposal.add_argument("--tag", action="append", default=[]); proposal.add_argument("--id", default="")
        if area == "practice":
            prep = actions.add_parser("prepare")
            prep.add_argument("id"); prep.add_argument("--brief", required=True); prep.add_argument("--checks", required=True)
            prep.add_argument("--fixtures", default="{}", help="JSON object of simple filenames to text")
            attach = actions.add_parser("attach")
            attach.add_argument("id"); attach.add_argument("--target", type=Path, required=True)
            attach.add_argument("--digest", required=True); attach.add_argument("--owner-approval", required=True)
        if area in ("noticeboard", "suggestions", "practice"):
            post = actions.add_parser("post" if area != "practice" else "record")
            post.add_argument("title"); post.add_argument("body"); post.add_argument("--evidence", action="append", default=[])
            if area == "practice":
                post.add_argument("--case", required=True); post.add_argument("--result", choices=("reported_pass", "reported_fail", "inconclusive"), required=True)
        decisions = {"workshop": ("approved", "rejected", "withdrawn"), "noticeboard": ("closed",),
                     "suggestions": ("accepted", "declined", "implemented"), "practice": ("owner_accepted", "owner_rejected")}
        decision = actions.add_parser("decide")
        decision.add_argument("id"); decision.add_argument("decision", choices=decisions[area])
        decision.add_argument("--digest", required=True); decision.add_argument("--owner-approval", required=True)
        if area == "workshop":
            decision.add_argument("--revision", type=int, required=True)
    host_parser = commands.add_parser("host-facilities", help=argparse.SUPPRESS)
    return host_parser


def dispatch(cx, root, args):
    initialize(cx)
    project = project_key(args.project)
    if args.action in ("list", "show"):
        return browse(cx, args.command, project, query=getattr(args, "query", ""), item_id=getattr(args, "id", ""), owner=True)
    if args.action == "decide":
        return owner_decision(cx, args.command, args.id, args.decision, args.digest, args.owner_approval,
                              revision=getattr(args, "revision", None), project=project)
    if args.action == "attach":
        bounded(args.owner_approval, 120, "owner approval")
        case = cx.execute("SELECT * FROM practice_cases WHERE id=? AND project=?", (args.id, project)).fetchone()
        if not case or case["digest"] != args.digest:
            raise ValueError("Review the original project case and its digest first")
        with cx:
            cx.execute("INSERT OR IGNORE INTO practice_projects VALUES(?,?)", (args.id, project_key(args.target)))
            audit(cx, "practice_attach", args.id, args.owner_approval)
        return dict(id=args.id, linked=True)
    payload = dict(area=args.command)
    if args.action == "prepare":
        with cx:
            cx.execute("BEGIN IMMEDIATE")
            return prepare(cx, root, project, "owner", dict(item_id=args.id, brief=args.brief, checks=args.checks,
                                                              fixtures=json.loads(args.fixtures)))
    if args.action == "propose":
        if args.file.is_symlink():
            raise ValueError("Contribution source symlink rejected")
        fd = os.open(args.file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as source:
            import stat
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Contribution must be a regular single-link text file")
            content = source.read(MAX_CONTENT + 1)
        payload.update(title=args.title, body=args.purpose, content=content, kind=args.kind,
                       evidence=args.evidence, tags=args.tag, item_id=args.id)
    else:
        payload.update(title=args.title, body=args.body, evidence=args.evidence)
        if args.command == "practice":
            payload.update(item_id=args.case, state=args.result)
    with cx:
        cx.execute("BEGIN IMMEDIATE")
        return publish(cx, project, "owner", "owner-command", payload, owner=True)
