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
        "manifest_offset": offset,
        "manifest": manifest[offset:offset + limit],
        "next_offset": offset + limit if offset + limit < len(manifest) else None,
    }


def node(state, node_id):
    for entry in state["dossier"]["nodes"]:
        if entry["id"] == node_id:
            return {"dossier_sha256": state["dossier_sha256"],
                    "source_ref": state["source_design_job"] + "#" + node_id,
                    "node": entry}
    raise ValueError("Design node is not in this frozen dossier")
