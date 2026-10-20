"""Frozen dossier handoff, immutable versions and bounded reads."""
import json
import tempfile
import sys
import time
from pathlib import Path
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / "payload")]
import design_integration as integration
import game_scaffold as game
import village
from studios import Studios
from studio_store import encoded


def accepted():
    review = dict(verdict="accept", checks={key: True for key in game.AUDIT_CHECKS},
                  findings=[], reason="The design question is resolved.")
    chosen = dict(title="The gate game", root_answer="Make a gate game about changing plate states.", contract={"player_goal": "Open the gate"})
    root = dict(id="G0", parent=None, depth=0, question="What should this studio make?",
                answer="Build a small game around reading a gate and manipulating its linked plates.",
                state="split", children=["G0.1", "G0.2", "G0.3", "G0.4", "G0.5"],
                audited=True, audit=review)
    nodes = [root]
    for i in range(1, 6):
        nodes.append(dict(id="G0." + str(i), parent="G0", depth=1,
            question="What is the complete rule for system " + str(i) + "?",
            answer="The rule defines the plate state, gate response and resulting player feedback.",
            state="leaf", children=[], audited=True, audit=review,
            leaf=dict(deliverable="A bounded rule table for the gate and floor plate states.",
                instruction="Describe each gate and plate state, its transition and the player-visible result.",
                inputs=["game promise"], outputs=["rule table"], depends_on=[],
                sufficiency_check="The table identifies each state and its resulting gate behaviour.",
                evidence=["reviewed rule table"])))
    return dict(status="complete", phase="complete", selected=chosen,
                context={"constraints": ["Portable C workstation"]}, candidates=[],
                nodes=nodes, final_audit=review)


class IntegrationFreezeTests(unittest.TestCase):
    def test_freeze_is_versioned_and_preserves_every_node(self):
        design = accepted()
        state = integration.freeze("design:1", design)
        digest = state["dossier_sha256"]
        design["nodes"][1]["answer"] = "Changed after freeze"
        self.assertNotEqual(state["dossier"]["nodes"][1]["answer"], design["nodes"][1]["answer"])
        self.assertEqual(integration.freeze("design:1", accepted())["dossier_sha256"], digest)
        self.assertEqual([n["source_ref"] for n in state["manifest"]],
                         ["design:1#" + n["id"] for n in state["dossier"]["nodes"]])
        self.assertEqual(integration.report(state, 0, 2)["next_offset"], 2)
        self.assertEqual(integration.report(state, 2, 100)["next_offset"], None)
        self.assertEqual(integration.node(state, "G0.1")["node"]["id"], "G0.1")
        self.assertEqual(state["work_orders"], [])
        self.assertEqual({n["decision_status"] for n in state["manifest"]}, {"unclassified"})

    def test_rejects_unfinished_or_rejected_dossiers(self):
        design = accepted()
        design["status"] = "paused"
        with self.assertRaises(ValueError):integration.freeze("design:1", design)
        design = accepted()
        design["final_audit"]["verdict"] = "revise"
        design["final_audit"]["checks"]["checkable"] = False
        design["final_audit"]["findings"] = ["Missing check"]
        with self.assertRaises(ValueError):integration.freeze("design:1", design)
        design = accepted()
        design["nodes"][2]["leaf"]["depends_on"] = ["missing"]
        with self.assertRaises(ValueError):integration.freeze("design:1", design)

    def test_context_lists_every_prerequisite_id(self):
        design = accepted()
        extra = json.loads(json.dumps(design["nodes"][-1]))
        extra["id"] = "G0.6"
        extra["question"] = "How does the sixth system interact with the plates?"
        extra["leaf"]["depends_on"] = ["G0." + str(i) for i in range(1, 6)]
        design["nodes"][0]["children"].append("G0.6")
        design["nodes"].append(extra)
        state = integration.freeze("design:1", design)
        state["cursor"] = len(state["manifest"]) - 1
        packet = integration.context(state)
        self.assertEqual([d["id"] for d in packet["prerequisites"]],
                         extra["leaf"]["depends_on"])

    def test_multiple_batches_cover_one_node_without_repeating_decisions(self):
        state = integration.freeze("design:1", accepted())
        state["phase"] = "inventory"
        quote = state["dossier"]["nodes"][0]["answer"][:40]
        row = lambda claim: dict(claim=claim, status="settled", quote=quote, question="")
        first = integration.inventory(dict(decisions=[row("The player reads the gate.")],
                                           coverage="First gate rule", more=True), state)
        state["partial_decisions"]