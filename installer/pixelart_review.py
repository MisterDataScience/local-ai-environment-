"""Owner review of generated pixel-art batches, using durable decisions."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import time
import zipfile

ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
TAG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Review:
    def __init__(self, root: Path):
        self.root = Path(root)
        if self.root.is_symlink():
            raise PermissionError("Review root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "review.sqlite"
        with self.connect() as cx:
            cx.execute("""CREATE TABLE IF NOT EXISTS decisions(
                event INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT NOT NULL,
                sprite TEXT NOT NULL, decision TEXT NOT NULL, note TEXT NOT NULL,
                actor TEXT NOT NULL, created INTEGER NOT NULL)""")
            cx.execute("CREATE INDEX IF NOT EXISTS decisions_lookup ON decisions(batch,sprite,event)")

    def connect(self):
        cx = sqlite3.connect(self.db, timeout=30)
        cx.row_factory = sqlite3.Row
        return cx

    def paths(self, batch: str, sprite: str | None = None):
        if not isinstance(batch, str) or not ID.fullmatch(batch):
            raise ValueError("Invalid batch ID")
        directory = self.root / batch
        if directory.is_symlink() or not (directory / "batch.json").is_file():
            raise ValueError("Unknown batch")
        if sprite is None:
            return directory
        if not isinstance(sprite, str) or not ID.fullmatch(sprite):
            raise ValueError("Invalid sprite ID")
        receipt = directory / "records" / (sprite + ".json")
        image = directory / "sprites" / (sprite + ".png")
        if receipt.is_symlink() or image.is_symlink() or not receipt.is_file() or not image.is_file():
            raise ValueError("Sprite is not in the batch")
        return receipt, image

    def _record(self, batch: str, sprite: str, *, image_data=False):
        receipt, image = self.paths(batch, sprite)
        record = json.loads(receipt.read_text(encoding="utf-8"))
        if (record.get("id") != sprite or record.get("batch") != batch or
                record.get("file") != "sprites/" + sprite + ".png"):
            raise ValueError("Sprite receipt does not match its batch")
        data = image.read_bytes()
        if hashlib.sha256(data).hexdigest() != record.get("sha256"):
            raise ValueError("Sprite content hash mismatch")
        if image_data:
            record["png"] = base64.b64encode(data).decode("ascii")
        return record

    def page(self, batch: str, *, offset=0, limit=40, tag=""):
        directory = self.paths(batch)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 40:
            raise ValueError("Invalid gallery page")
        if tag and (not isinstance(tag, str) or not TAG.fullmatch(tag)):
            raise ValueError("Invalid tag")
        ids = sorted(p.stem for p in (directory / "records").glob("*.json") if ID.fullmatch(p.stem))
        if tag:
            ids = [sid for sid in ids if tag in self._record(batch, sid).get("tags", [])]
        selected = ids[offset:offset + limit]
        with self.connect() as cx:
            decisions = {r["sprite"]: dict(r) for r in cx.execute(
                "SELECT * FROM decisions WHERE batch=? ORDER BY event", (batch,))}
        records = []
        for sid in selected:
            record = self._record(batch, sid, image_data=True)
            record["review"] = {"decision": decisions[sid]["decision"], "note": decisions[sid]["note"]} if sid in decisions else {"decision": "pending", "note": ""}
            records.append(record)
        return {"batch": batch, "total": len(ids), "offset": offset, "next_offset": offset + len(records),
                "has_more": offset + len(records) < len(ids), "records": records}

    def decide(self, batch: str, sprite: str, decision: str, note: str = ""):
        self._record(batch, sprite)
        if decision not in ("keep", "reject", "pending") or not isinstance(note, str) or len(note) > 1000:
            raise ValueError("Invalid review decision")
        with self.connect() as cx:
            cx.execute("INSERT INTO decisions(batch,sprite,decision,note,actor,created) VALUES(?,?,?,?,?,?)",
                       (batch, sprite, decision, note, "owner", int(time.time())))
            event = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"event": event, "batch": batch, "sprite": sprite, "decision": decision, "note": note}

    def export_kept(self, batch: str) -> bytes:
        self.paths(batch)
        with self.connect() as cx:
            latest = {r["sprite"]: r["decision"] for r in cx.execute(
                "SELECT sprite,decision FROM decisions WHERE batch=? ORDER BY event", (batch,))}
        kept = [self._record(batch, sid) for sid, decision in sorted(latest.items()) if decision == "keep"]
        if not kept:
            raise ValueError("No kept sprites")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for record in kept:
                _, image = self.paths(batch, record["id"])
                archive.writestr(record["file"], image.read_bytes())
            archive.writestr("manifest.json", json.dumps({"batch": batch, "records": kept}, sort_keys=True))
        return output.getvalue()
