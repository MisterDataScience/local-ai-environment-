"""Adaptive, resumable reverse scaffold for studio game design.

The tree records design decisions, not an arbitrary number of generated tasks.
Every accepted node is audited, leaves have an observable sufficiency check, and
dependencies are validated references to earlier accepted design decisions.
"""
import json


DEPARTMENTS = (
    ("experience", "Player Experience Designer", "Invent a distinct player experience and explain the repeated player action, meaningful choice, intended feeling, and smallest satisfying demo. Avoid defaulting to platforming or combat."),
    ("systems", "Game Systems Designer", "Identify rules and state that make the experience work. Explain ownership, transitions, inputs, outputs, edge cases, and dependencies. Do not assume a genre."),
    ("content", "World and Content Designer", "Explore the spaces, characters, objects, pacing, onboarding, and presentation needed to make this experience legible. Avoid decorative content without a player purpose."),
    ("technical", "Technical and Production Designer", "Assess the studio's actual tools and constraints. Identify risks, smallest experiments, and dependencies. Do not start implementation or invent unprovided engine facts."),
)

MIN_CHILDREN = 2
MAX_CHILDREN = 5
MAX_ROOT_CHILDREN = 7
MIN_ROOT_CHILDREN = 5
MAX_NODES = 5000
AUDIT_CHECKS = ("contract_met", "specific", "traceable", "complete_for_stage", "checkable")


def initial_state(context):
    return {
        "version": 2, "status": "running", "phase": "candidates", "candidate_index": 0,
        "context": context, "candidates": [], "selected": None, "nodes": [],
        "queue": [], "pending": None, "audit_index": 0, "leaf_count": 0,
        "audit_count": 0, "retry": 0, "final_audit": None,
    }


def parse(text):
    text = text.strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Planning agent must return one JSON object")
    return value


def candidate(value, expected_id):
    fields = {"id", "title", "player_experience", "repeated_activity", "meaningful_choice", "distinctive_hook", "demo_shape", "uncertainty"}
    if not isinstance(value, dict) or set(value) != fields or value["id"] != expected_id:
        raise ValueError("Candidate has missing, extra, or mismatched fields")
    for key in fields - {"id"}:
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 900:
            raise ValueError("Candidate field must be a concise, non-empty string: " + key)
    return value


def selection(value, candidates):
    if not isinstance(value, dict) or set(value) != {"selected_id", "title", "root_answer", "contract", "first_questions", "rejected"}:
        raise ValueError("Lead Designer selection has an invalid shape")
    ids = {c["id"] for c in candidates}
    if value["selected_id"] not in ids:
        raise ValueError("Selected concept was not proposed by a department")
    for key in ("title", "root_answer"):
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 1800:
            raise ValueError("Selection requires a concise " + key)
    contract_fields = {"player_goal", "repeated_play", "intended_appeal", "demo_boundary", "completion_rule", "exclusions"}
    if (not isinstance(value["contract"], dict) or set(value["contract"]) != contract_fields
            or any(not isinstance(x, str) or not x.strip() for x in value["contract"].values())
            or not isinstance(value["rejected"], list)):
        raise ValueError("Selection contract or rejected alternatives are invalid")
    children = value["first_questions"]
    if not isinstance(children, list) or not MIN_ROOT_CHILDREN <= len(children) <= MAX_ROOT_CHILDREN:
        raise ValueError("The game root must branch into five to seven distinct design questions")
    questions = set()
    for child in children:
        if not isinstance(child, str) or len(child.strip()) < 12 or len(child) > 300 or child in questions:
            raise ValueError("Root branches must be distinct, specific questions")
        questions.add(child)
    return value


def expansion(value, node, attempt, max_children=MAX_CHILDREN):
    if not isinstance(value, dict) or set(value) != {"answer", "disposition", "children", "leaf"}:
        raise ValueError("Branch expansion has an invalid shape")
    if not isinstance(value["answer"], str) or not 30 <= len(value["answer"].strip()) <= 2400:
        raise ValueError("Each design question needs a substantive answer")
    depth = node["depth"]
    disposition = value["disposition"]
    if disposition == "split":
        children = value["children"]
        if not isinstance(children, list) or not MIN_CHILDREN <= len(children) <= min(MAX_CHILDREN, max_children):
            raise ValueError("A split must create two to five necessary narrower questions")
        seen = set()
        for child in children:
            if not isinstance(child, str) or len(child.strip()) < 16 or len(child) > 400 or child in seen:
                raise ValueError("Child questions must be distinct, specific, and bounded")
            seen.add(child)
        if value["leaf"] is not None:
            raise ValueError("Split branches cannot also contain a leaf decision")
    elif disposition == "leaf":
        if value["children"] not in ([], None):
            raise ValueError("Terminal leaves cannot have children")
        leaf = value["leaf"]
        required = {"deliverable", "instruction", "inputs", "outputs", "depends_on", "sufficiency_check", "evidence"}
        if not isinstance(leaf, dict) or set(leaf) != required:
            raise ValueError("Design leaf is missing its bounded deliverable or review contract")
        for key in ("deliverable", "instruction", "sufficiency_check"):
            if not isinstance(leaf[key], str) or len(leaf[key].strip()) < 25 or len(leaf[key]) > 1200:
                raise ValueError("Design leaf needs a concrete " + key)
        for key in ("inputs", "outputs", "depends_on", "evidence"):
            if not isinstance(leaf[key], list) or len(leaf[key]) > 20 or any(not isinstance(x, str) or not x.strip() for x in leaf[key]):
                raise ValueError("Design leaf field must be a bounded list: " + key)
        if not leaf["inputs"] or not leaf["outputs"] or not leaf["evidence"]:
            raise ValueError("Design leaf must name inputs, a reviewable output, and evidence")
        if len(set(leaf["depends_on"])) != len(leaf["depends_on"]):
            raise ValueError("Design leaf repeats a prerequisite")
    else:
        raise ValueError("Disposition must be split or leaf")
    return value


def audit(value):
    required = {"verdict", "checks", "findings", "reason"}
    if not isinstance(value, dict) or set(value) != required or value["verdict"] not in ("accept", "revise"):
        raise ValueError("Audit has an invalid shape")
    checks = value["checks"]
    if not isinstance(checks, dict) or set(checks) != set(AUDIT_CHECKS) or any(type(v) is not bool for v in checks.values()):
        raise ValueError("Audit must report every sufficiency check as true or false")
    if not isinstance(value["findings"], list) or len(value["findings"]) > 8 or any(not isinstance(x, str) for x in value["findings"]):
        raise ValueError("Audit findings are malformed")
    if not isinstance(value["reason"], str) or not value["reason"].strip():
        raise ValueError("Audit reason is required")
    if value["verdict"] == "revise" and not value["findings"]:
        raise ValueError("A rejected branch must name repairable findings")
    if value["verdict"] == "accept" and not all(checks.values()):
        raise ValueError("Audit cannot accept while a sufficiency check is false")
    if value["verdict"] == "revise" and all(checks.values()):
        raise ValueError("Audit cannot reject while every sufficiency check is true")
    return value


def validate_dependencies(node, nodes):
    """Require prerequisite IDs to name earlier, accepted design-decision leaves."""
    leaf = node.get("leaf", {})
    known = {n["id"]: n for n in nodes}
    positions = {n["id"]: i for i, n in enumerate(nodes)}
    node_position = positions.get(node.get("id"), len(nodes))
    errors = []
    for dep in leaf.get("depends_on", []):
        if dep == node.get("id"):
            errors.append("self dependency in " + node["id"])
            continue
        target = known.get(dep)
        if target is None:
            errors.append("unknown prerequisite " + dep + " in " + node["id"])
        elif target.get("state") != "leaf" or not target.get("audited"):
            errors.append("prerequisite is not an accepted design decision: " + dep)
        elif positions[dep] >= node_position:
            errors.append("prerequisite must refer to an earlier decision: " + dep)
    return errors


def tree_counts(nodes):
    return {"nodes": len(nodes), "leaves": sum(n["state"] == "leaf" for n in nodes),
            "audited": sum(n.get("audited", False) for n in nodes),
            "max_depth": max((n["depth"] for n in nodes), default=0)}


def structural_errors(state):
    nodes = state["nodes"]
    errors = []
    ids = [n["id"] for n in nodes]
    if len(nodes) > MAX_NODES:
        errors.append("tree exceeds node safety limit")
    if len(ids) != len(set(ids)):
        errors.append("duplicate node IDs")
    known = set(ids)
    roots = [n for n in nodes if n.get("parent") is None]
    if len(roots) != 1 or not roots or roots[0].get("id") != "G0":
        errors.append("tree must have exactly one G0 root")
    for n in nodes:
        if not n.get("audited"):
            errors.append("unaudited node " + n["id"])
        elif not isinstance(n.get("audit"), dict):
            errors.append("missing audit record for " + n["id"])
        else:
            try:
                audit(n["audit"])
            except ValueError as e:
                errors.append("invalid audit record for " + n["id"] + ": " + str(e))
        if n.get("parent") is not None and n["parent"] not in known:
            errors.append("missing parent for " + n["id"])
        if n.get("state") not in ("split", "leaf"):
            errors.append("unfinished node " + n["id"])
        children = n.get("children", [])
        if n.get("state") == "split":
            low, high = (MIN_ROOT_CHILDREN, MAX_ROOT_CHILDREN) if n.get("id") == "G0" else (MIN_CHILDREN, MAX_CHILDREN)
            if not isinstance(children, list) or not low <= len(children) <= high:
                errors.append("invalid split size for " + n["id"])
            for child_id in children:
                child = next((x for x in nodes if x["id"] == child_id), None)
                if child is None or child.get("parent") != n["id"] or child.get("depth") != n.get("depth", 0) + 1:
                    errors.append("invalid child link from " + n["id"])
        if n.get("state") == "leaf":
            if children:
                errors.append("terminal leaf has children " + n["id"])
            try:
                expansion({"answer": n["answer"], "disposition": "leaf", "children": [], "leaf": n["leaf"]}, {"depth": n["depth"]}, 0)
            except (KeyError, ValueError) as e:
                errors.append("invalid leaf " + n["id"] + ": " + str(e))
            errors.extend(validate_dependencies(n, nodes))
    return errors
