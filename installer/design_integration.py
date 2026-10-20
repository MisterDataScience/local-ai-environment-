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
        "systems": [],
        "system_links": [],
        "mapping_queue": [],
        "mapping_cursor": 0,
        "mapping_enabled": False,
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
        "system_count": len(state.get("systems", [])),
        "mapping_done": state.get("mapping_cursor", 0),
        "mapping_total": len(state.get("mapping_queue", [])),
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
    ancestor_chain = [a["id"] for a in ancestors]
    if len(ancestors) > 3:
        ancestors = [ancestors[0], *ancestors[-2:]]
    selected = state["dossier"]["selected"]
    related = []
    for dep in entry["prerequisites"]:
        decision = by_id[dep]
        related.append({"id": dep, "answer": decision["answer"],
                        "resolution": state["resolutions"].get(dep)})
    return {"source_design_job": state["source_design_job"],
            "dossier_sha256": state["dossier_sha256"],
            "design_version_sha256": state["design_version_sha256"],
            "selected": {"title": selected["title"], "root_answer": selected["root_answer"][:500],
                         "contract": {key: str(val)[:300] for key, val in selected["contract"].items()}},
            "node": current, "ancestor_chain": ancestor_chain,
            "ancestors": ancestors, "prerequisites": related,
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


def accept_resolution(state, question, result, review, node_id=None):
    game_scaffold.audit(review)
    if review["verdict"] != "accept":
        raise ValueError("A rejected resolution cannot enter the versioned dossier")
    node_id = node_id or state["manifest"][state["cursor"]]["id"]
    if node_id not in {entry["id"] for entry in state["manifest"]}:
        raise ValueError("Resolution references an unknown design node")
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
        if state.get("mapping_enabled"):
            begin_system_mapping(state)
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


def begin_system_mapping(state):
    """Rebuild a deterministic, cited system index from the complete ledger."""
    if state["phase"] != "inventory_complete" or state["cursor"] != len(state["manifest"]):
        raise ValueError("A complete decision ledger is required before mapping systems")
    if state.get("pending") or state.get("partial_decisions") or any(
            issue.get("resolved") is False for issue in state["issues"]):
        raise ValueError("Unresolved design questions prevent system mapping")
    node_ids = {entry["id"] for entry in state["manifest"]}
    decisions = state["decisions"]
    manifest_by_id = {entry["id"]: entry for entry in state["manifest"]}
    if (len(state.get("reviewed_nodes", [])) != len(node_ids) or
            set(state["reviewed_nodes"]) != node_ids or
            {row["node_id"] for row in decisions} != node_ids or
            len({row["id"] for row in decisions}) != len(decisions) or
            any(row["source_ref"] != manifest_by_id[row["node_id"]]["source_ref"] or
                row["status"] == "open" for row in decisions)):
        raise ValueError("The decision ledger contains duplicate, missing or open decisions")
    root = state["manifest"][0]["id"]
    by_id = {entry["id"]: entry for entry in state["manifest"]}
    def system_for(node_id):
        seen = set()
        while by_id[node_id]["parent"] not in (None, root):
            if node_id in seen:
                raise ValueError("Cycle in dossier ancestry")
            seen.add(node_id)
            node_id = by_id[node_id]["parent"]
        return node_id
    systems = {}
    for row in decisions:
        sid = system_for(row["node_id"])
        if sid not in systems:
            source = next(n for n in state["dossier"]["nodes"] if n["id"] == sid)
            systems[sid] = {"id": sid, "name": source["question"][:160],
                            "source_ref": state["source_design_job"] + "#" + sid,
                            "decision_ids": [], "summary": ""}
        systems[sid]["decision_ids"].append(row["id"])
    links = []
    seen = set()
    for entry in state["manifest"]:
        target = system_for(entry["id"])
        for prerequisite in entry["prerequisites"]:
            origin = system_for(prerequisite)
            if origin != target and origin in systems and target in systems:
                key = (origin, target, prerequisite, entry["id"])
                if key not in seen:
                    seen.add(key)
                    links.append({"from": origin, "to": target,
                                  "prerequisite_node": prerequisite,
                                  "dependent_node": entry["id"]})
    state["systems"] = list(systems.values())
    state["system_links"] = links
    queue = []
    for system in state["systems"]:
        for offset in range(0, len(system["decision_ids"]), 4):
            queue.append({"kind": "system", "system": system["id"], "offset": offset})
    # Compare each system pair after its own batches have been reviewed.
    for i, left in enumerate(state["systems"]):
        for right in state["systems"][i + 1:]:
            link_count = sum({link["from"], link["to"]} == {left["id"], right["id"]}
                             for link in links)
            for offset in range(0, max(1, link_count), 32):
                queue.append({"kind": "pair", "left": left["id"],
                              "right": right["id"], "offset": offset})
    state["mapping_queue"] = queue
    state["mapping_cursor"] = 0
    state["mapping_enabled"] = True
    state["pending"] = None
    state["retry"] = 0
    state["phase"] = "system_mapping"
    state["status"] = "system_mapping_running"


def context_for_node(state, node_id):
    index = next((i for i, entry in enumerate(state["manifest"]) if entry["id"] == node_id), None)
    if index is None:
        raise ValueError("Unknown design node for system question")
    return context(dict(state, cursor=index))


def mapping_packet(state):
    if state["phase"] not in ("system_mapping", "system_map_audit"):
        raise ValueError("System mapping is not active")
    item = state["mapping_queue"][state["mapping_cursor"]]
    systems = {system["id"]: system for system in state["systems"]}
    decisions = {row["id"]: row for row in state["decisions"]}
    def excerpt(ids):
        return [{"id": key, "node_id": decisions[key]["node_id"],
                 "status": decisions[key]["status"], "claim": decisions[key]["claim"][:350],
                 "quote": decisions[key]["quote"][:300],
                 "source_ref": decisions[key]["source_ref"]}
                for key in ids]
    if item["kind"] == "system":
        system = systems[item["system"]]
        return {"item": item, "system": system, "decisions": excerpt(
            system["decision_ids"][item["offset"]:item["offset"] + 4]),
            "links": [link for link in state["system_links"]
                      if system["id"] in (link["from"], link["to"])][:24],
            "selected": {key: str(value)[:300] for key, value in state["dossier"]["selected"]["contract"].items()},
            "design_version_sha256": state["design_version_sha256"]}
    left, right = systems[item["left"]], systems[item["right"]]
    return {"item": item, "systems": [
        {"id": system["id"], "name": system["name"],
         "summary": system["summary"][:600],
         "decision_count": len(system["decision_ids"]),
         "sample": excerpt(system["decision_ids"][:3])}
        for system in (left, right)],
        "links": [link for link in state["system_links"]
                  if {link["from"], link["to"]} == {left["id"], right["id"]}][
                      item["offset"]:item["offset"] + 32],
        "selected": state["dossier"]["selected"]["contract"],
        "design_version_sha256": state["design_version_sha256"]}


def mapping_result(value, packet):
    if not isinstance(value, dict) or set(value) != {"summary", "issues"}:
        raise ValueError("System map proposal has an invalid shape")
    if not isinstance(value["summary"], str) or not 20 <= len(value["summary"].strip()) <= 600:
        raise ValueError("System map needs a bounded summary")
    issues = value["issues"]
    if not isinstance(issues, list) or len(issues) > 1:
        raise ValueError("System map must return at most one issue per saved turn")
    available = {d["id"]: d["node_id"] for d in packet.get("decisions", [])}
    for system in packet.get("systems", []):
        available.update({d["id"]: d["node_id"] for d in system["sample"]})
    checked = []
    for issue in issues:
        if not isinstance(issue, dict) or set(issue) != {"node_id", "decision_ids", "question"}:
            raise ValueError("System issue needs node, cited decisions and a question")
        ids = issue["decision_ids"]
        if not isinstance(ids, list) or not ids or len(ids) > 6 or len(set(ids)) != len(ids):
            raise ValueError("System issue must cite bounded unique decisions")
        if any(key not in available for key in ids) or issue["node_id"] not in (
                available[key] for key in ids):
            raise ValueError("System issue must target one of its cited design nodes")
        if not isinstance(issue["question"], str) or not 15 <= len(issue["question"].strip()) <= 600:
            raise ValueError("System issue needs a specific Lead Designer question")
        checked.append(issue)
    return {"summary": value["summary"].strip(), "issues": checked}


def commit_mapping(state, result):
    item = state["mapping_queue"][state["mapping_cursor"]]
    if result["issues"]:
        issue = result["issues"][0]
        node_id = issue["node_id"]
        if sum(row["node_id"] == node_id for row in state["revision_history"]) >= 2:
            state["phase"] = "blocked"
            state["status"] = "blocked"
            state["issues"].append(dict(kind="mapping_unresolved", **issue))
            return
        state["pending"] = {"question": issue["question"],
                            "reason": "Audited system mapping found a design conflict or missing rule.",
                            "node_id": node_id, "decision_ids": issue["decision_ids"]}
        state["issues"].append(dict(kind="system_gap", resolved=False, **issue))
        state["phase"] = "mapping_lead_resolve"
        return
    if item["kind"] == "system":
        system = next(s for s in state["systems"] if s["id"] == item["system"])
        system["summary"] = result["summary"]
    state["mapping_cursor"] += 1
    state["pending"] = None
    state["retry"] = 0
    if state["mapping_cursor"] == len(state["mapping_queue"]):
        covered = [key for system in state["systems"] for key in system["decision_ids"]]
        if sorted(covered) != sorted(row["id"] for row in state["decisions"]):
            raise ValueError("System map omitted or repeated a decision")
        if any(issue.get("resolved") is False for issue in state["issues"]):
            raise ValueError("System map still contains unresolved design questions")
        state["phase"] = "system_map_complete"
        state["status"] = "awaiting_work_orders"
    else:
        state["phase"] = "system_mapping"


def restart_inventory_after_mapping_resolution(state):
    """Re-inventory the changed design version before trusting any system assignment."""
    state["decisions"] = []
    state["reviewed_nodes"] = []
    state["partial_decisions"] = []
    state["batches_for_node"] = 0
    state["cursor"] = 0
    state["systems"] = []
    state["system_links"] = []
    state["mapping_queue"] = []
    state["mapping_cursor"] = 0
    state["pending"] = None
    state["retry"] = 0
    for entry in state["manifest"]:
        entry["decision_status"] = "unclassified"
    state["phase"] = "inventory"
    state["status"] = "inventory_running"


def systems_page(state, offset=0, limit=100, link_offset=0):
    if (type(offset) is not int or offset < 0 or type(limit) is not int or
            not 1 <= limit <= 100 or type(link_offset) is not int or link_offset < 0):
        raise ValueError("Invalid system page")
    rows = state.get("systems", [])
    links = state.get("system_links", [])
    return {"phase": state["phase"], "design_version_sha256": state["design_version_sha256"],
            "total": len(rows), "offset": offset, "systems": rows[offset:offset + limit],
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "links": links[link_offset:link_offset + limit],
            "link_total": len(links), "link_offset": link_offset,
            "next_link_offset": link_offset + limit if link_offset + limit < len(links) else None,
            "mapping_done": state.get("mapping_cursor", 0),
            "mapping_total": len(state.get("mapping_queue", []))}
