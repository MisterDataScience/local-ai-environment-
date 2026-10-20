"""Frozen dossier handoff, immutable versions and bounded reads."""
import json
import tempfile
import sys
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
    chosen = dict(title="The gate game", contract={"player_goal": "Open the gate"})
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

    def test_bounded_lookup(self):
        state = integration.freeze("design:1", accepted())
        for offset, limit in [(-1, 1), (0, 0), (0, 101), (True, 1)]:
            with self.assertRaises(ValueError):integration.report(state, offset, limit)
        with self.assertRaises(ValueError):integration.node(state, "missing")



class IntegrationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        class Engine:
            pass
        engine = Engine()
        engine.root = root / "control"
        engine.root.mkdir()
        engine.captain = {"enabled": True, "model_id": "local"}
        engine.mode_status = lambda: {"mode": "max", "transitioning": False, "error": None}
        self.studios = Studios(engine, lambda path: village.connect(path, test_encrypted=True))
        self.addCleanup(self.studios.shutdown)
        self.institution = self.studios.store.create("Gate studio", "Make a small gate game")["id"]
        self.design_job = "studio-job:test-design"
        with self.studios.store.db() as cx, cx:
            cx.execute("INSERT INTO studio_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (self.design_job, self.institution, "", "design", "complete",
                        "{}", encoded({"design": accepted()}), 0, 0, 0, "", 1))

    def test_persistent_handoff_is_idempotent_and_institution_scoped(self):
        request = {"operation": "prepare_integration", "institution": self.institution,
                   "job": self.design_job}
        first = self.studios.execute(request)
        self.assertEqual(first["manifest_total"], 6)
        self.assertEqual(first["status"], "awaiting_decision_inventory")
        self.assertEqual(self.studios.execute(request)["id"], first["id"])
        self.assertEqual(self.studios.execute({"operation": "integration_report",
            "institution": self.institution, "job": first["id"], "limit": 2})["next_offset"], 2)
        fetched = self.studios.execute({"operation": "integration_node",
            "institution": self.institution, "job": first["id"], "node": "G0.1"})
        self.assertEqual(fetched["source_ref"], self.design_job + "#G0.1")
        with self.studios.store.db() as cx, cx:
            source = json.loads(cx.execute("SELECT progress FROM studio_jobs WHERE id=?",
                         (self.design_job,)).fetchone()[0])
            source["design"]["nodes"][1]["answer"] = "Changed source"
            cx.execute("UPDATE studio_jobs SET progress=? WHERE id=?",
                       (encoded(source), self.design_job))
        unchanged = self.studios.execute({"operation": "integration_node",
            "institution": self.institution, "job": first["id"], "node": "G0.1"})
        self.assertEqual(unchanged["node"], fetched["node"])
        view = self.studios.execute({"operation": "view", "institution": self.institution})
        frozen = next(row for row in view["jobs"] if row["id"] == first["id"])
        self.assertNotIn("dossier", frozen["progress"])
        with self.assertRaises(ValueError):
            self.studios.execute({"operation": "integration_report",
                                  "institution": "studio:other", "job": first["id"]})
        with self.assertRaises(ValueError):
            self.studios.resume(first["id"])

    def test_incomplete_source_cannot_be_frozen(self):
        with self.studios.store.db() as cx, cx:
            cx.execute("UPDATE studio_jobs SET state='paused' WHERE id=?", (self.design_job,))
        with self.assertRaises(ValueError):
            self.studios.execute({"operation": "prepare_integration",
                                  "institution": self.institution, "job": self.design_job})

if __name__ == "__main__":
    unittest.main()
