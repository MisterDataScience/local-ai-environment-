"""Frozen, traceable input for the studio design integration department.

This stage copies the accepted design job exactly once. It does not interpret
rules or create implementation tasks. Later bounded passes consume the manifest
and retrieve original nodes by ID rather than loading the full tree at once.
"""
import json

import game_scaffold
from studio_store import encoded, sha


def freeze(design_job_id, design):
    if not isinstance(design, dict) or design.get("status") != "complete" or design.get("phase") != "complete":
        raise ValueError("Finish the Lead Designer dossier before integration")
    final = design.get("final_audit")
    if not isinstance(final, dict):
        raise ValueError("The dossier needs a final audit")
    game_scaffold.audit(final)
    if final["verdict"] != "accept":
        raise ValueError("The final design audit did not accept the dossier")
    errors = game_scaffold.structural_errors(design)
    if errors:
        raise ValueError("The dossier has structural errors: " + str(errors[:8]))
    if any(node["audit"]["verdict"] != "accept" for node in design["nodes"]):
        raise ValueError("Every design node must have an accepting audit")
    if not isinstance(design_job_id, str) or not design_job_id:
        raise ValueError("A source design job ID is required")

    # JSON round-trip detaches the snapshot from the mutable planning state.
    dossier = json.loads(encoded({
        "selected": design["selected"],
        "context": design["context"],
        "candidates": design["candidates"],
        "nodes": design["nodes"],
        "final_audit": final,
    }))
    digest = sha(encoded(dossier))
    manifest = []
    for node in dossier["nodes"]:
        manifest.append({
            "id": node["id"],
            "parent": node["parent"],
            "children": list(node["children"]),
            "kind": node["state"],
            "prerequisites": list(node["leaf"]["depends_on"]) if node["state"] == "leaf" else [],
            "source_ref": design_job_id + "#" + node["id"],
            "decision_status": "unclassified",
        })
    return {
        "version": 1,
        "phase": "frozen",
        "status": "awaiting_decision_inventory",
        "source_design_job": design_job_id,
        "dossier_sha256": digest,
        "dossier": dossier,
        "manifest": manifest,
        "cursor": 0,
        "decisions": [],
        "work_orders": [],
        "issues": [],
        "resolutions": {},
        "revision_history": [],
        "design_version_sha256": digest,
        "pending": None,
        "retry": 0,
        "reviewed_nodes": [],
        "partial_decisions": [],
        "batches_for_node": 0,
    }


def report(state, offset=0, limit=100):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid manifest page")
    manifest = state["manifest"]
    return {
        "version": state["version"],
        "phase": state["phase"],
        "status": state["status"],
        "source_design_job": state["source_design_job"],
        "dossier_sha256": state["dossier_sha256"],
        "selected": state["dossier"]["selected"],
        "counts": game_scaffold.tree_counts(state["dossier"]["nodes"]),
        "manifest_total": len(manifest),
        "processed_nodes": len(state.get("reviewed_nodes", [])),
        "decision_count": len(state.get("decisions", [])),
        "issue_count": len(state.get("issues", [])),
        "design_version_sha256": state.get("design_version_sha256", state["dossier_sha256"]),
        "pending_question": (state.get("pending") or {}).get("question"),
        "unresolved_issues": [issue for issue in state.get("issues", []) if issue.get("resolved") is not True][-5:],
        "manifest_offset": offset,
        "manifest": manifest[offset:offset + limit],
        "next_offset": offset + limit if offset + limit < len(manifest) else None,
    }


def node(state, node_id):
    for entry in state["dossier"]["nodes"]:
        if entry["id"] == node_id:
            return {"dossier_sha256": state["dossier_sha256"],
                    "source_ref": state["source_design_job"] + "#" + node_id,
                    "node": entry, "resolution": state.get("resolutions", {}).get(node_id),
                    "issues": [issue for issue in state.get("issues", []) if issue.get("node_id") == node_id]}
    raise ValueError("Design node is not in this frozen dossier")

STATUSES = {"settled", "hypothesis", "deferred", "open"}
MAX_DECISIONS_PER_NODE = 4


def context(state):
    """A bounded packet containing the original promise, local ancestry and inputs."""
    cursor = state["cursor"]
    entry = state["manifest"][cursor]
    by_id = {n["id"]: n for n in state["dossier"]["nodes"]}
    current = by_id[entry["id"]]
    ancestors = []
    parent = current["parent"]
    while parent:
        ancestor = by_id[parent]
        ancestors.append({"id": parent, "question": ancestor["question"],
                          "answer": ancestor["answer"],
                          "resolution": state["resolutions"].get(parent)})
        parent = ancestor["parent"]
    ancestors.reverse()
    if len(ancestors) > 3:
        ancestors = [ancestors[0], *ancestors[-2:]]
    selected = state["dossier"]["selected"]
    related = []
    for dep in entry["prerequisites"][:4]:
        decision = by_id[dep]
        related.append({"id": dep, "answer": decision["answer"],
                        "resolution": state["resolutions"].get(dep)})
    return {"source_design_job": state["source_design_job"],
            "dossier_sha256": state["dossier_sha256"],
            "design_version_sha256": state["design_version_sha256"],
            "selected": {"title": selected["title"], "root_answer": selected["root_answer"][:500],
                         "contract": {key: str(val)[:300] for key, val in selected["contract"].items()}},
            "node": current, "ancestors": ancestors, "prerequisites": related,
            "approved_lessons": [
                {"id": doc["id"], "title": doc["title"], "excerpt": doc["text"][:350]}
                for doc in state["dossier"]["context"].get("approved_lessons", [])[:2]],
            "resolution": state["resolutions"].get(entry["id"]),
            "already_recorded": [{"id": d["id"], "claim": d["claim"]} for d in state.get("partial_decisions", [])[-4:]],
            "recorded_count": len(state.get("partial_decisions", []))}


def lead_result(value):
    if not isinstance(value, dict) or set(value) != {"content", "status", "reason"}:
        raise ValueError("Lead Designer resolution has an invalid shape")
    if value["status"] not in STATUSES or not isinstance(value["content"], str) or not 30 <= len(value["content"].strip()) <= 6000:
        raise ValueError("Lead Designer must supply a bounded design result")
    if not isinstance(value["reason"], str) or not value["reason"].strip() or len(value["reason"]) > 1000:
        raise ValueError("Lead Designer resolution needs a reason")
    return value


def accept_resolution(state, question, result, review):
    game_scaffold.audit(review)
    if review["verdict"] != "accept":
        raise ValueError("A rejected resolution cannot enter the versioned dossier")
    node_id = state["manifest"][state["cursor"]]["id"]
    previous = state["resolutions"].get(node_id)
    record = {"node_id": node_id, "question": question,
              "content": result["content"], "status": result["status"],
              "reason": result["reason"], "audit": review,
              "supersedes": previous["sha256"] if previous else None}
    record["sha256"] = sha(encoded(record))
    state["resolutions"][node_id] = record
    state["revision_history"].append(record)
    state["design_version_sha256"] = sha(encoded({
        "dossier_sha256": state["dossier_sha256"],
        "resolutions": state["resolutions"]}))
    return record


def inventory(value, state):
    """Validate one model proposal against the exact frozen node and resolution."""
    if not isinstance(value, dict) or set(value) != {"decisions", "coverage", "more"}:
        raise ValueError("Decision inventory has an invalid shape")
    if type(value["more"]) is not bool:
        raise ValueError("Inventory must say whether this node has more decisions")
    rows = value["decisions"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_DECISIONS_PER_NODE:
        raise ValueError("Inventory must contain one to four decisions for the node")
    if not isinstance(value["coverage"], str) or not value["coverage"].strip() or len(value["coverage"]) > 1000:
        raise ValueError("Inventory must explain how it covered the node")
    entry = state["manifest"][state["cursor"]]
    node = state["dossier"]["nodes"][state["cursor"]]
    resolution = state["resolutions"].get(entry["id"])
    if node["id"] != entry["id"]:
        raise ValueError("Dossier and manifest order disagree")
    allowed = [node["answer"]]
    if resolution:
        allowed.append(resolution["content"])
    cleaned = []
    batch_claims = set()
    for index, row in enumerate(rows, len(state.get("partial_decisions", [])) + 1):
        if not isinstance(row, dict) or set(row) != {"claim", "status", "quote", "question"}:
            raise ValueError("Decision entry has an invalid shape")
        if row["status"] not in STATUSES:
            raise ValueError("Unknown decision status")
        if not isinstance(row["claim"], str) or not 12 <= len(row["claim"].strip()) <= 900:
            raise ValueError("Decision needs a bounded claim")
        if not isinstance(row["quote"], str) or len(row["quote"].strip()) < 12 or len(row["quote"]) > 600 or not any(row["quote"] in source for source in allowed):
            raise ValueError("Decision must quote its own node answer or accepted resolution exactly")
        if not isinstance(row["question"], str) or len(row["question"]) > 600:
            raise ValueError("Decision question is invalid")
        if row["status"] == "open" and not row["question"].strip():
            raise ValueError("An open decision requires a question for the Lead Designer")
        if row["status"] != "open" and row["question"].strip():
            raise ValueError("Only open decisions may return a question")
        if node["state"] == "leaf" and resolution and row["status"] != "open" and row["quote"] not in resolution["content"]:
            raise ValueError("A settled design leaf must cite its reviewed deliverable")
        if node["state"] == "leaf" and not resolution and row["status"] != "open":
            raise ValueError("A leaf instruction is not a completed rule")
        if resolution and resolution["status"] == "open" and row["status"] != "open":
            raise ValueError("An unresolved Lead Designer result cannot settle a rule")
        if row["claim"] in batch_claims or any(row["claim"] == previous["claim"] for previous in state.get("partial_decisions", [])):
            raise ValueError("A decision was repeated in this node")
        batch_claims.add(row["claim"])
        cleaned.append({"id": entry["id"] + ":D" + str(index), "node_id": entry["id"],
                        "claim": row["claim"], "status": row["status"],
                        "quote": row["quote"], "question": row["question"],
                        "source_ref": entry["source_ref"],
                        "resolution_sha256": resolution["sha256"] if resolution and row["quote"] in resolution["content"] else None,
                        "design_version_sha256": state["design_version_sha256"]})
    return {"decisions": cleaned, "coverage": value["coverage"], "more": value["more"]}


def commit_inventory(state, inventory_result):
    node_id = state["manifest"][state["cursor"]]["id"]
    if any(row["status"] == "open" for row in inventory_result["decisions"]):
        raise ValueError("Resolve open decisions before advancing the inventory")
    if inventory_result["more"]:
        raise ValueError("Cannot finish a node while the inventory says more decisions remain")
    if node_id in state["reviewed_nodes"]:
        raise ValueError("Node is already recorded in this inventory")
    rows = state.get("partial_decisions", []) + inventory_result["decisions"]
    resolution = state["resolutions"].get(node_id)
    if resolution and not any(row["resolution_sha256"] == resolution["sha256"] for row in rows):
        raise ValueError("The accepted Lead Designer resolution is not cited by any decision")
    state["decisions"].extend(rows)
    state["reviewed_nodes"].append(node_id)
    statuses = {d["status"] for d in rows}
    state["manifest"][state["cursor"]]["decision_status"] = (
        next(iter(statuses)) if len(statuses) == 1 else "mixed")
    state["cursor"] += 1
    state["partial_decisions"] = []
    state["batches_for_node"] = 0
    state["pending"] = None
    state["retry"] = 0
    if state["cursor"] == len(state["manifest"]):
        if len(state["reviewed_nodes"]) != len(state["manifest"]):
            raise ValueError("Decision inventory did not cover every design node")
        state["phase"] = "inventory_complete"
        state["status"] = "awaiting_system_mapping"
    else:
        state["phase"] = "inventory"
        state["status"] = "inventory_running"


def decisions_page(state, offset=0, limit=100):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid decision page")
    rows = state["decisions"]
    return {"dossier_sha256": state["dossier_sha256"],
            "design_version_sha256": state["design_version_sha256"],
            "total": len(rows), "offset": offset, "decisions": rows[offset:offset + limit],
            "next_offset": offset + limit if offset + limit < len(rows) else None}
