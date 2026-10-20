"""Frozen, traceable input for the studio design integration department.

This stage copies the accepted design job exactly once. It does not interpret
rules or create implementation tasks. Later bounded passes consume the manifest
and retrieve original nodes by ID rather than loading the full tree at once.
"""
import json
import re

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
        "system_interactions": [],
        "mapping_queue": [],
        "mapping_cursor": 0,
        "mapping_enabled": False,
        "work_orders": [],
        "work_order_deferred": [],
        "work_order_queue": [],
        "work_order_cursor": 0,
        "work_orders_enabled": False,
        "work_order_gate": None,
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
        "work_order_count": len(state.get("work_orders", [])),
        "work_order_done": state.get("work_order_cursor", 0),
        "work_order_total": len(state.get("work_order_queue", [])),
        "work_order_gate": state.get("work_order_gate"),
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
    """Start bounded Integrator passes over the complete decision ledger."""
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
    state["systems"] = []
    state["system_links"] = []
    state["mapping_queue"] = [
        {"kind": "group", "offset": offset}
        for offset in range(0, len(decisions), 4)]
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


def _relevant_systems(state, decision_rows):
    tokens = set()
    node_by_id = {node["id"]: node for node in state["dossier"]["nodes"]}
    for row in decision_rows:
        text = row["claim"] + " " + row["quote"] + " " + node_by_id[row["node_id"]]["question"]
        tokens.update(re.findall(r"[a-z0-9]{4,}", text.casefold()))
    ranked = []
    for system in state["systems"]:
        words = set(re.findall(r"[a-z0-9]{4,}",
                               (system["name"] + " " + system["summary"]).casefold()))
        ranked.append((len(tokens & words), system["id"], system))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [{"id": row["id"], "name": row["name"],
             "summary": row["summary"][:180]} for _, _, row in ranked[:10]]


def mapping_packet(state):
    if state["phase"] not in ("system_mapping", "system_map_audit"):
        raise ValueError("System mapping is not active")
    item = state["mapping_queue"][state["mapping_cursor"]]
    systems = {system["id"]: system for system in state["systems"]}
    decisions = {row["id"]: row for row in state["decisions"]}
    def excerpt(ids):
        node_index = {node["id"]: node for node in state["dossier"]["nodes"]}
        return [{"id": key, "node_id": decisions[key]["node_id"],
                 "status": decisions[key]["status"], "claim": decisions[key]["claim"][:350],
                 "quote": decisions[key]["quote"][:300],
                 "source_ref": decisions[key]["source_ref"],
                 "design_question": node_index[decisions[key]["node_id"]]["question"][:220]}
                for key in ids]
    if item["kind"] == "group":
        batch = state["decisions"][item["offset"]:item["offset"] + 4]
        return {"item": item, "decisions": excerpt([row["id"] for row in batch]),
            "known_systems": _relevant_systems(state, batch),
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
        "selected": {key: str(value)[:300] for key, value in state["dossier"]["selected"]["contract"].items()},
        "design_version_sha256": state["design_version_sha256"]}


def mapping_result(value, packet):
    if not isinstance(value, dict):
        raise ValueError("System mapping proposal must be an object")
    item = packet["item"]
    if "issues" not in value:
        raise ValueError("System mapping proposal must include issues")
    issues = value["issues"]
    available = {d["id"]: d["node_id"] for d in packet.get("decisions", [])}
    for system in packet.get("systems", []):
        available.update({d["id"]: d["node_id"] for d in system["sample"]})
    checked = []
    if not isinstance(issues, list) or len(issues) > 1:
        raise ValueError("System mapping may return at most one issue per saved turn")
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
    if item["kind"] == "group":
        if not isinstance(value, dict) or set(value) != {"systems", "issues"}:
            raise ValueError("System grouping proposal has an invalid shape")
        groups = value["systems"]
        if not isinstance(groups, list) or not 1 <= len(groups) <= 4:
            raise ValueError("A grouping pass must assign decisions to one to four systems")
        available_ids = {row["id"] for row in packet["decisions"]}
        assigned = []
        cleaned = []
        names = set()
        for group in groups:
            if not isinstance(group, dict) or set(group) != {"id", "name", "decision_ids", "summary"}:
                raise ValueError("A system needs an optional known ID, name, decisions and summary")
            if not isinstance(group["id"], str):
                raise ValueError("System ID must be a string")
            name = group["name"]
            if not isinstance(name, str) or not 3 <= len(name.strip()) <= 100:
                raise ValueError("System name is invalid")
            key = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:72]
            if not key or key in names:
                raise ValueError("System names must be distinct within a pass")
            names.add(key)
            known = {row["id"]: row for row in packet.get("known_systems", [])}
            if group["id"] and (group["id"] not in known or
                                  known[group["id"]]["name"] != name.strip()):
                raise ValueError("A reused system must use its exact supplied ID and name")
            ids = group["decision_ids"]
            if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or any(x not in available_ids for x in ids):
                raise ValueError("A system must cite unique decisions from this batch")
            if not isinstance(group["summary"], str) or not 20 <= len(group["summary"].strip()) <= 600:
                raise ValueError("System summary is invalid")
            assigned.extend(ids)
            cleaned.append({"id": group["id"] or "system:" + key, "name": name.strip(),
                            "decision_ids": ids, "summary": group["summary"].strip()})
        if sorted(assigned) != sorted(available_ids):
            raise ValueError("Every decision in the batch must belong to exactly one system")
        if not isinstance(issues, list) or len(issues) > 1:
            raise ValueError("System grouping may return at most one design issue")
        return {"systems": cleaned, "issues": checked}
    if not isinstance(value, dict) or set(value) != {"summary", "issues"}:
        raise ValueError("System interaction proposal has an invalid shape")
    if not isinstance(value["summary"], str) or not 20 <= len(value["summary"].strip()) <= 600:
        raise ValueError("System interaction needs a bounded summary")
    if not isinstance(issues, list) or len(issues) > 1:
        raise ValueError("System interaction may return at most one design issue")
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
    if item["kind"] == "group":
        by_decision = {row["id"]: row for row in state["decisions"]}
        for proposal in result["systems"]:
            system = next((row for row in state["systems"] if row["id"] == proposal["id"]), None)
            if system is None:
                system = {"id": proposal["id"], "name": proposal["name"],
                          "decision_ids": [], "summary": ""}
                state["systems"].append(system)
            elif system["name"].casefold() != proposal["name"].casefold():
                raise ValueError("A reused system ID must keep its approved name")
            system["decision_ids"].extend(proposal["decision_ids"])
            system["summary"] = (system["summary"] + " " + proposal["summary"])[-1200:].strip()
            for decision_id in proposal["decision_ids"]:
                row = by_decision[decision_id]
                row["system_id"] = system["id"]
        state["mapping_cursor"] += 1
        state["pending"] = None
        state["retry"] = 0
        if state["mapping_cursor"] == len(state["mapping_queue"]):
            _queue_system_interactions(state)
            return
        state["phase"] = "system_mapping"
        return
    if item["kind"] == "pair":
        state["system_interactions"].append({
            "left": item["left"], "right": item["right"],
            "link_offset": item.get("offset", 0),
            "review": result["summary"]})
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


def _queue_system_interactions(state):
    """Derive system edges from accepted decision assignments and queue reviews."""
    decision_by_node = {}
    for row in state["decisions"]:
        decision_by_node.setdefault(row["node_id"], set()).add(row["system_id"])
    links = []
    seen = set()
    for entry in state["manifest"]:
        for prerequisite in entry["prerequisites"]:
            for origin in decision_by_node.get(prerequisite, set()):
                for target in decision_by_node.get(entry["id"], set()):
                    if origin == target:
                        continue
                    key = (origin, target, prerequisite, entry["id"])
                    if key not in seen:
                        seen.add(key)
                        links.append({"from": origin, "to": target,
                                      "prerequisite_node": prerequisite,
                                      "dependent_node": entry["id"]})
    state["system_links"] = links
    pairs = []
    for i, left in enumerate(state["systems"]):
        for right in state["systems"][i + 1:]:
            link_count = sum({link["from"], link["to"]} == {left["id"], right["id"]}
                             for link in links)
            for offset in range(0, max(1, link_count), 32):
                pairs.append({"kind": "pair", "left": left["id"],
                              "right": right["id"], "offset": offset})
    state["system_interactions"] = []
    state["mapping_queue"] = pairs
    state["mapping_cursor"] = 0
    if not pairs:
        _finish_system_mapping(state)
    else:
        state["phase"] = "system_mapping"


def _finish_system_mapping(state):
    assigned = [row.get("system_id") for row in state["decisions"]]
    valid = {system["id"] for system in state["systems"]}
    if len(assigned) != len(state["decisions"]) or any(key not in valid for key in assigned):
        raise ValueError("System mapping omitted or repeated a decision")
    if any(link["from"] not in valid or link["to"] not in valid
           for link in state["system_links"]):
        raise ValueError("System link references an unknown system")
    if any(issue.get("resolved") is False for issue in state["issues"]):
        raise ValueError("System map still contains unresolved design questions")
    state["phase"] = "system_map_complete"
    state["status"] = "awaiting_work_orders"
    if state.get("work_orders_enabled"):
        begin_work_order_planning(state)


def restart_inventory_after_mapping_resolution(state):
    """Re-inventory the changed design version before trusting any system assignment."""
    state["decisions"] = []
    state["reviewed_nodes"] = []
    state["partial_decisions"] = []
    state["batches_for_node"] = 0
    state["cursor"] = 0
    state["systems"] = []
    state["system_links"] = []
    state["system_interactions"] = []
    state["mapping_queue"] = []
    state["mapping_cursor"] = 0
    state["work_orders"] = []
    state["work_order_deferred"] = []
    state["work_order_queue"] = []
    state["work_order_cursor"] = 0
    state["work_order_gate"] = None
    state["pending"] = None
    state["retry"] = 0
    for entry in state["manifest"]:
        entry["decision_status"] = "unclassified"
    state["phase"] = "inventory"
    state["status"] = "inventory_running"


def systems_page(state, offset=0, limit=100, link_offset=0,
                 system_id=None, decision_offset=0):
    if (type(offset) is not int or offset < 0 or type(limit) is not int or
            not 1 <= limit <= 100 or type(link_offset) is not int or link_offset < 0 or
            type(decision_offset) is not int or decision_offset < 0):
        raise ValueError("Invalid system page")
    rows = state.get("systems", [])
    links = state.get("system_links", [])
    if system_id is not None:
        system = next((row for row in rows if row["id"] == system_id), None)
        if system is None:
            raise ValueError("System is not in this mapping")
        ids = system["decision_ids"]
        return {"phase": state["phase"], "system": {key: value for key, value in system.items()
                if key != "decision_ids"}, "decision_total": len(ids),
                "decision_offset": decision_offset,
                "decision_ids": ids[decision_offset:decision_offset + limit],
                "next_decision_offset": decision_offset + limit
                    if decision_offset + limit < len(ids) else None}
    summaries = [{key: value for key, value in system.items() if key != "decision_ids"}
                 | {"decision_count": len(system["decision_ids"])}
                 for system in rows[offset:offset + limit]]
    return {"phase": state["phase"], "design_version_sha256": state["design_version_sha256"],
            "total": len(rows), "offset": offset, "systems": summaries,
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "links": links[link_offset:link_offset + limit],
            "link_total": len(links), "link_offset": link_offset,
            "next_link_offset": link_offset + limit if link_offset + limit < len(links) else None,
            "mapping_done": state.get("mapping_cursor", 0),
            "mapping_total": len(state.get("mapping_queue", []))}


WORK_ORDER_CHECKS = {
    "automated_test", "simulation", "content_inspection", "asset_inspection",
    "playtest", "experiment"
}
WORK_ORDER_KINDS = {"code", "content", "asset", "experiment", "integration"}


def begin_work_order_planning(state):
    """Start saved production-planning passes over an accepted system map."""
    if state.get("phase") != "system_map_complete":
        raise ValueError("An accepted system map is required before work-order planning")
    if state.get("pending") or any(issue.get("resolved") is False for issue in state.get("issues", [])):
        raise ValueError("Unresolved design questions prevent work-order planning")
    decisions = state.get("decisions", [])
    systems = state.get("systems", [])
    system_ids = {system.get("id") for system in systems}
    decision_ids = {row.get("id") for row in decisions}
    assigned = [decision_id for system in systems for decision_id in system.get("decision_ids", [])]
    if (len(decision_ids) != len(decisions) or len(assigned) != len(decision_ids) or
            set(assigned) != decision_ids):
        raise ValueError("The system map must assign every decision exactly once")
    # Older accepted maps stored membership only on each system record.
    owner = {decision_id: system["id"] for system in systems
             for decision_id in system.get("decision_ids", [])}
    for row in decisions:
        if row.get("system_id") not in system_ids:
            row["system_id"] = owner[row["id"]]
        if row["system_id"] != owner[row["id"]]:
            raise ValueError("Decision and system membership records disagree")
    state["work_orders"] = []
    state["work_order_deferred"] = []
    state["work_order_queue"] = []
    for system in systems:
        ids = system["decision_ids"]
        for offset in range(0, len(ids), 4):
            state["work_order_queue"].append({"system": system["id"], "offset": offset})
    state["work_order_cursor"] = 0
    state["work_orders_enabled"] = True
    state["mapping_enabled"] = True
    state["work_order_gate"] = None
    state["pending"] = None
    state["retry"] = 0
    if not state["work_order_queue"]:
        state["work_order_gate"] = validate_work_orders(state)
        if not state["work_order_gate"]["passed"]:
            state["phase"] = "blocked"
            state["status"] = "blocked"
            raise ValueError("Work-order handoff gate failed")
        state["phase"] = "work_order_complete"
        state["status"] = "awaiting_implementation"
    else:
        state["phase"] = "work_order_planning"
        state["status"] = "work_order_planning_running"


def work_order_packet(state):
    if state.get("phase") not in ("work_order_planning", "work_order_audit"):
        raise ValueError("Work-order planning is not active")
    item = state["work_order_queue"][state["work_order_cursor"]]
    system = next((row for row in state["systems"] if row["id"] == item["system"]), None)
    if system is None:
        raise ValueError("Work-order system is missing")
    decisions = {row["id"]: row for row in state["decisions"]}
    nodes = {row["id"]: row for row in state["dossier"]["nodes"]}
    manifest = {row["id"]: row for row in state["manifest"]}
    ids = system["decision_ids"][item["offset"]:item["offset"] + 4]
    batch = []
    prerequisite_ids = set()
    for key in ids:
        decision = decisions[key]
        required_nodes = set(manifest[decision["node_id"]]["prerequisites"])
        required_decisions = [row["id"] for row in state["decisions"]
                              if row["node_id"] in required_nodes]
        batch.append({"id": key, "node_id": decision["node_id"],
                      "claim": decision["claim"][:500], "status": decision["status"],
                      "quote": decision["quote"][:400], "source_ref": decision["source_ref"],
                      "system_id": system["id"], "system_name": system["name"],
                      "required_prerequisite_decision_ids": required_decisions})
        prerequisite_ids.update(required_nodes)
    prerequisite_decisions = [
        {"id": decision["id"], "node_id": decision["node_id"],
         "claim": decision["claim"][:300], "status": decision["status"]}
        for decision in state["decisions"] if decision["node_id"] in prerequisite_ids]
    selected = state["dossier"]["selected"]
    return {"item": item,
            "system": {key: value for key, value in system.items() if key != "decision_ids"},
            "decisions": batch,
            "prerequisite_decisions": prerequisite_decisions,
            "selected": {"title": selected["title"],
                         "root_answer": selected["root_answer"][:500],
                         "contract": {key: str(value)[:300]
                                      for key, value in selected["contract"].items()}},
            "studio_constraints": state["dossier"].get("context", {}).get("constraints", [])[:12],
            "approved_lessons": [{"id": row["id"], "title": row["title"],
                                  "excerpt": row["text"][:300]}
                                 for row in state["dossier"].get("context", {}).get("approved_lessons", [])[:2]],
            "design_version_sha256": state["design_version_sha256"]}


def work_order_result(value, packet):
    if not isinstance(value, dict) or set(value) != {"work_orders", "deferred", "issues"}:
        raise ValueError("Work-order proposal has an invalid shape")
    if not isinstance(value["issues"], list) or len(value["issues"]) > 1:
        raise ValueError("A planning pass may return at most one design issue")
    available = {row["id"]: row for row in packet["decisions"]}
    all_decisions = {row["id"]: row for row in packet["decisions"] + packet["prerequisite_decisions"]}
    checked_issues = []
    for issue in value["issues"]:
        if not isinstance(issue, dict) or set(issue) != {"node_id", "decision_ids", "question"}:
            raise ValueError("A planning issue needs a cited node, decisions and question")
        ids = issue["decision_ids"]
        if not isinstance(ids, list) or not ids or len(ids) > 6 or len(ids) != len(set(ids)):
            raise ValueError("A planning issue must cite bounded unique decisions")
        if any(not isinstance(key, str) or key not in all_decisions for key in ids) or not isinstance(issue["node_id"], str) or issue["node_id"] not in (
                all_decisions[key]["node_id"] for key in ids):
            raise ValueError("A planning issue must refer to supplied decisions from its node")
        if not isinstance(issue["question"], str) or not 15 <= len(issue["question"].strip()) <= 600:
            raise ValueError("A planning issue needs a specific Lead Designer question")
        checked_issues.append({**issue, "decision_ids": list(ids), "question": issue["question"].strip()})
    tasks = value["work_orders"]
    deferred = value["deferred"]
    if not isinstance(tasks, list) or len(tasks) > 8 or not isinstance(deferred, list) or len(deferred) > 4:
        raise ValueError("Work orders and deferrals must fit the bounded planning pass")
    if checked_issues:
        if tasks or deferred:
            raise ValueError("Return a design issue before creating work for the affected batch")
        return {"work_orders": [], "deferred": [], "issues": checked_issues}
    assigned = []
    experiments = set()
    checked_tasks = []
    valid_prerequisites = {row["id"] for row in packet["prerequisite_decisions"]}
    for task in tasks:
        fields = {"title", "kind", "decision_ids", "inputs", "outputs",
                  "prerequisite_decision_ids", "responsible_role", "done_when", "check", "evidence"}
        if not isinstance(task, dict) or set(task) != fields:
            raise ValueError("A work order has an invalid shape")
        if not isinstance(task["title"], str) or not 4 <= len(task["title"].strip()) <= 120:
            raise ValueError("A work order needs a bounded title")
        if not isinstance(task["kind"], str) or task["kind"] not in WORK_ORDER_KINDS:
            raise ValueError("Unknown work-order kind")
        refs = task["decision_ids"]
        if (not isinstance(refs, list) or not refs or any(not isinstance(key, str) for key in refs) or
                len(refs) != len(set(refs)) or any(key not in available for key in refs)):
            raise ValueError("A work order must cite decisions from its supplied system batch")
        prerequisites = task["prerequisite_decision_ids"]
        task_prerequisite_ids = {key for decision_id in refs
                                 for key in available[decision_id]["required_prerequisite_decision_ids"]}
        if (not isinstance(prerequisites, list) or any(not isinstance(key, str) for key in prerequisites) or
                len(prerequisites) != len(set(prerequisites)) or
                any(key not in valid_prerequisites or key not in task_prerequisite_ids
                    for key in prerequisites) or set(prerequisites) != task_prerequisite_ids):
            raise ValueError("A work order must preserve all supplied design prerequisites for its decisions")
        for field in ("inputs", "outputs", "evidence"):
            values = task[field]
            if (not isinstance(values, list) or not 1 <= len(values) <= 8 or
                    any(not isinstance(text, str) or not 3 <= len(text.strip()) <= 300 for text in values)):
                raise ValueError("Work-order inputs, outputs and evidence need bounded descriptions")
        if not isinstance(task["responsible_role"], str) or not 3 <= len(task["responsible_role"].strip()) <= 80:
            raise ValueError("A work order needs a responsible specialist role")
        if not isinstance(task["done_when"], str) or not 20 <= len(task["done_when"].strip()) <= 500:
            raise ValueError("A work order needs an observable completion condition")
        check = task["check"]
        if (not isinstance(check, dict) or set(check) != {"method", "procedure", "expected_result"} or
                not isinstance(check["method"], str) or check["method"] not in WORK_ORDER_CHECKS or
                any(not isinstance(check[key], str) or not 12 <= len(check[key].strip()) <= 600
                    for key in ("procedure", "expected_result"))):
            raise ValueError("A work order needs a planned, design-based acceptance check")
        if check["method"] == "experiment":
            experiments.update(key for key in refs if available[key]["status"] == "hypothesis")
        if any(available[key]["status"] == "deferred" for key in refs):
            raise ValueError("A deferred design decision cannot be scheduled for implementation")
        if any(all_decisions[key]["status"] == "deferred" for key in prerequisites):
            raise ValueError("A work order cannot depend on a deferred design decision")
        assigned.extend(refs)
        checked_tasks.append({"title": task["title"].strip(), "kind": task["kind"],
            "system_id": packet["system"]["id"], "decision_ids": list(refs),
            "inputs": [value.strip() for value in task["inputs"]],
            "outputs": [value.strip() for value in task["outputs"]],
            "prerequisite_decision_ids": list(prerequisites),
            "responsible_role": task["responsible_role"].strip(),
            "done_when": task["done_when"].strip(),
            "check": {key: (value.strip() if isinstance(value, str) else value)
                      for key, value in check.items()},
            "evidence": [value.strip() for value in task["evidence"]],
            "check_status": "planned"})
    deferred_ids = []
    for row in deferred:
        if not isinstance(row, dict) or set(row) != {"decision_id", "reason"}:
            raise ValueError("A deferral needs one decision ID and a reason")
        key = row["decision_id"]
        if not isinstance(key, str) or key not in available:
            raise ValueError("A deferral must reference a supplied design decision")
        if not isinstance(row["reason"], str) or not 15 <= len(row["reason"].strip()) <= 400:
            raise ValueError("A deferral needs a clear reason")
        if available[key]["status"] != "deferred":
            blockers = available[key]["required_prerequisite_decision_ids"]
            if not any(all_decisions[dependency]["status"] == "deferred"
                       for dependency in blockers if dependency in all_decisions):
                raise ValueError("A settled decision may be deferred only when an approved prerequisite is deferred")
        deferred_ids.append(key)
    batch_ids = set(available)
    if set(assigned) & set(deferred_ids):
        raise ValueError("A design decision cannot be both planned and deferred")
    if set(assigned) | set(deferred_ids) != batch_ids:
        raise ValueError("Every supplied decision must map to a work order or explicit deferral")
    missing_experiments = {key for key in batch_ids if available[key]["status"] == "hypothesis"} - experiments
    if missing_experiments:
        raise ValueError("Every hypothesis needs a planned experiment")
    return {"work_orders": checked_tasks,
            "deferred": [{"decision_id": row["decision_id"], "reason": row["reason"].strip()}
                         for row in deferred],
            "issues": checked_issues}


def commit_work_order_pass(state, result):
    item = state["work_order_queue"][state["work_order_cursor"]]
    if result["issues"]:
        issue = result["issues"][0]
        if sum(row.get("node_id") == issue["node_id"] for row in state["revision_history"]) >= 2:
            state["phase"] = "blocked"
            state["status"] = "blocked"
            state["issues"].append({"kind": "work_order_unresolved", **issue})
            return
        state["pending"] = {"question": issue["question"],
                            "reason": "Work-order planning found a missing or conflicting game rule.",
                            "node_id": issue["node_id"], "decision_ids": issue["decision_ids"]}
        state["issues"].append({"kind": "work_order_gap", "resolved": False, **issue})
        state["phase"] = "work_order_lead_resolve"
        return
    next_id = len(state["work_orders"]) + 1
    for task in result["work_orders"]:
        task = dict(task)
        task["id"] = "WO-" + str(next_id).zfill(4)
        next_id += 1
        task["status"] = "planned"
        task["depends_on"] = []
        state["work_orders"].append(task)
    state["work_order_deferred"].extend(result["deferred"])
    state["work_order_cursor"] += 1
    state["pending"] = None
    state["retry"] = 0
    if state["work_order_cursor"] == len(state["work_order_queue"]):
        gate = validate_work_orders(state)
        state["work_order_gate"] = gate
        if not gate["passed"]:
            state["phase"] = "blocked"
            state["status"] = "blocked"
            raise ValueError("Work-order handoff gate failed: " + "; ".join(gate["errors"][:5]))
        state["phase"] = "work_order_complete"
        state["status"] = "awaiting_implementation"
    else:
        state["phase"] = "work_order_planning"


def validate_work_orders(state):
    """Derive task dependencies and enforce traceability and acyclic scheduling."""
    errors = []
    decisions = {row["id"]: row for row in state.get("decisions", [])}
    decision_ids_by_node = {}
    for decision in decisions.values():
        decision_ids_by_node.setdefault(decision["node_id"], set()).add(decision["id"])
    required_by_node = {row["id"]: row["prerequisites"] for row in state.get("manifest", [])}
    orders = state.get("work_orders", [])
    by_id = {row.get("id"): row for row in orders}
    if len(by_id) != len(orders) or None in by_id:
        errors.append("Work-order IDs are missing or repeated")
    coverage = {}
    valid_systems = {row.get("id") for row in state.get("systems", [])}
    for order in orders:
        if order.get("system_id") not in valid_systems:
            errors.append("Work order " + str(order.get("id")) + " references an unknown system")
        refs = order.get("decision_ids", [])
        if (not isinstance(refs, list) or any(not isinstance(key, str) or key not in decisions for key in refs)):
            errors.append("Work order " + str(order.get("id")) + " references an unknown design decision")
            continue
        for decision_id in order.get("decision_ids", []):
            coverage.setdefault(decision_id, []).append(order["id"])
    deferred = {}
    for row in state.get("work_order_deferred", []):
        decision_id = row.get("decision_id")
        if decision_id not in decisions:
            errors.append("A deferral references an unknown design decision")
        else:
            deferred.setdefault(decision_id, []).append(row)
    for key, decision in decisions.items():
        tasks = coverage.get(key, [])
        defer_rows = deferred.get(key, [])
        if decision.get("status") == "deferred":
            if tasks or len(defer_rows) != 1:
                errors.append("Deferred decision " + key + " needs one explicit deferral and no implementation task")
        elif not tasks or defer_rows:
            errors.append("Decision " + key + " must be covered by a work order")
        if decision.get("status") == "hypothesis" and tasks and not any(
                by_id[task_id].get("check", {}).get("method") == "experiment"
                for task_id in tasks if task_id in by_id):
            errors.append("Hypothesis " + key + " needs an experiment work order")
    for order in orders:
        dependencies = set()
        expected_prerequisites = set()
        for decision_id in order.get("decision_ids", []):
            decision = decisions.get(decision_id)
            if decision:
                for node_id in required_by_node.get(decision["node_id"], []):
                    expected_prerequisites.update(decision_ids_by_node.get(node_id, set()))
        if set(order.get("prerequisite_decision_ids", [])) != expected_prerequisites:
            errors.append("Work order " + order["id"] + " omits or adds a design prerequisite")
        for decision_id in order.get("prerequisite_decision_ids", []):
            if decision_id not in decisions:
                errors.append("Work order " + order["id"] + " references an unknown prerequisite decision")
                continue
            prerequisites = coverage.get(decision_id, [])
            if not prerequisites:
                errors.append("Work order " + order["id"] + " depends on an uncovered decision")
            dependencies.update(key for key in prerequisites if key != order["id"])
        order["depends_on"] = sorted(dependencies)
    for key in by_id:
        for dependency in by_id[key].get("depends_on", []):
            if dependency not in by_id:
                errors.append("Work order " + key + " has an unknown dependency")
    visiting, visited = set(), set()
    def visit(key):
        if key in visiting:
            return False
        if key in visited:
            return True
        visiting.add(key)
        for dependency in by_id[key].get("depends_on", []):
            if dependency in by_id and not visit(dependency):
                return False
        visiting.remove(key)
        visited.add(key)
        return True
    for key in by_id:
        if key not in visited and not visit(key):
            errors.append("Work-order dependency graph contains a cycle")
            break
    return {"passed": not errors, "errors": errors,
            "decision_count": len(decisions), "work_order_count": len(orders),
            "deferred_count": len(state.get("work_order_deferred", [])),
            "dependency_count": sum(len(row.get("depends_on", [])) for row in orders),
            "design_version_sha256": state.get("design_version_sha256")}


def work_orders_page(state, offset=0, limit=100):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid work-order page")
    rows = state.get("work_orders", [])
    return {"phase": state.get("phase"), "status": state.get("status"),
            "total": len(rows), "offset": offset, "work_orders": rows[offset:offset + limit],
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "deferred": state.get("work_order_deferred", [])[offset:offset + limit],
            "gate": state.get("work_order_gate")}

