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
        state["partial_decisions"].extend(first["decisions"])
        with self.assertRaises(ValueError):
            integration.inventory(dict(decisions=[row("The player reads the gate.")],
                                       coverage="Repeated rule", more=False), state)
        second = integration.inventory(dict(decisions=[row("The player changes the plates.")],
                                            coverage="All remaining rules", more=False), state)
        integration.commit_inventory(state, second)
        self.assertEqual([d["id"] for d in state["decisions"]], ["G0:D1", "G0:D2"])
        self.assertEqual(state["cursor"], 1)
        self.assertEqual(state["partial_decisions"], [])

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

    def test_saved_inventory_resolves_leaves_and_one_rule_gap(self):
        frozen = self.studios.execute({"operation": "prepare_integration",
            "institution": self.institution, "job": self.design_job})
        with self.studios.store.db() as cx:
            progress = json.loads(cx.execute("SELECT progress FROM studio_jobs WHERE id=?",
                                              (frozen["id"],)).fetchone()[0])
        calls = []
        def answer(jid, system, packet):
            node_id = packet["node"]["id"]
            calls.append((node_id, packet.get("stage", "map")))
            if "Decision Mapper" in system:
                if node_id == "G0" and not packet.get("resolution"):
                    quote = packet["node"]["answer"][:40]
                    row = dict(claim="The gate activation rule still needs a precise definition.",
                               status="open", quote=quote,
                               question="Which exact plate state opens the gate?")
                else:
                    quote = (packet["resolution"]["content"] if packet.get("resolution")
                             else packet["node"]["answer"])[:40]
                    row = dict(claim="The gate follows the reviewed rule for " + node_id + ".",
                               status="settled", quote=quote, question="")
                return json.dumps(dict(decisions=[row], coverage="This node has one bounded rule.", more=False))
            if "Lead Designer returning" in system:
                return json.dumps(dict(content="The gate opens only when all three floor plates are pressed at once.",
                                       status="settled", reason="This specifies the state and result."))
            return json.dumps(dict(verdict="accept",
                checks={key: True for key in game.AUDIT_CHECKS}, findings=[],
                reason="The rule is sourced, specific and complete for this node."))
        self.studios.infer = answer
        done = False
        for _ in range(50):
            progress, done = self.studios.integration_step({"id": frozen["id"]}, progress)
            if done: break
        self.assertTrue(done)
        state = progress["integration"]
        self.assertEqual(state["phase"], "inventory_complete")
        self.assertEqual(len(state["reviewed_nodes"]), 6)
        self.assertEqual(len(state["decisions"]), 6)
        self.assertEqual(len(state["revision_history"]), 6)
        self.assertTrue(all(issue.get("resolved") for issue in state["issues"]))
        self.assertNotEqual(state["design_version_sha256"], state["dossier_sha256"])
        self.assertEqual(state["work_orders"], [])
        self.assertTrue(any(stage == "Lead Designer design resolution"
                            for _, stage in calls))

    def test_inventory_rejects_unsupported_claim_and_unfinished_leaf(self):
        state = integration.freeze(self.design_job, accepted())
        state["cursor"] = 1
        invalid = dict(decisions=[dict(claim="The gate opens on all combinations.",
            status="settled", quote="The rule defines the plate state",
            question="")], coverage="One gate rule", more=False)
        with self.assertRaises(ValueError):integration.inventory(invalid, state)
        invalid["decisions"][0]["status"] = "open"
        invalid["decisions"][0]["question"] = "What actually opens the gate?"
        invalid["decisions"][0]["quote"] = "not a real source excerpt"
        with self.assertRaises(ValueError):integration.inventory(invalid, state)

    def test_inventory_requires_an_approved_lead_designer(self):
        frozen = self.studios.execute({"operation": "prepare_integration",
            "institution": self.institution, "job": self.design_job})
        with self.assertRaises(ValueError):
            self.studios.execute({"operation": "run_integration",
                                  "institution": self.institution, "job": frozen["id"]})

    def test_incomplete_source_cannot_be_frozen(self):
        with self.studios.store.db() as cx, cx:
            cx.execute("UPDATE studio_jobs SET state='paused' WHERE id=?", (self.design_job,))
        with self.assertRaises(ValueError):
            self.studios.execute({"operation": "prepare_integration",
                                  "institution": self.institution, "job": self.design_job})


class SystemMappingTests(unittest.TestCase):
    def ledger(self):
        design = accepted()
        design["nodes"][2]["leaf"]["depends_on"] = ["G0.1"]
        state = integration.freeze("design:1", design)
        state["decisions"] = [
            dict(id=entry["id"] + ":D1", node_id=entry["id"],
                 status="settled", claim="The reviewed rule for " + entry["id"],
                 quote="The rule defines the plate state",
                 source_ref=entry["source_ref"],
                 design_version_sha256=state["design_version_sha256"])
            for entry in state["manifest"]]
        state["cursor"] = len(state["manifest"])
        state["reviewed_nodes"] = [entry["id"] for entry in state["manifest"]]
        state["phase"] = "inventory_complete"
        return state

    def test_system_index_covers_all_decisions_and_explicit_links(self):
        state = self.ledger()
        integration.begin_system_mapping(state)
        self.assertEqual(len(state["systems"]), 6)
        self.assertEqual({d for system in state["systems"] for d in system["decision_ids"]},
                         {row["id"] for row in state["decisions"]})
        self.assertIn(dict(**{"from": "G0.1", "to": "G0.2"},
                           prerequisite_node="G0.1", dependent_node="G0.2"),
                      state["system_links"])
        self.assertEqual(integration.systems_page(state, 0, 2)["next_offset"], 2)
        self.assertEqual(state["work_orders"], [])
        with self.assertRaises(ValueError):
            integration.begin_system_mapping(state)

    def test_mapping_rejects_uncited_or_unrelated_lead_question(self):
        state = self.ledger()
        integration.begin_system_mapping(state)
        packet = integration.mapping_packet(state)
        result = dict(summary="The gate contains an explicit player-facing rule.",
                      issues=[dict(node_id="G0.2", decision_ids=["missing"],
                                   question="Which plate combination opens the gate?")])
        with self.assertRaises(ValueError):
            integration.mapping_result(result, packet)
        result["issues"][0]["decision_ids"] = [packet["decisions"][0]["id"]]
        with self.assertRaises(ValueError):
            integration.mapping_result(result, packet)

    def test_audited_gap_returns_to_lead_then_invalidates_old_map(self):
        state = self.ledger()
        integration.begin_system_mapping(state)
        packet = integration.mapping_packet(state)
        cited = packet["decisions"][0]
        proposal = integration.mapping_result(dict(
            summary="The gate state depends on a rule not yet specified.",
            issues=[dict(node_id=cited["node_id"], decision_ids=[cited["id"]],
                         question="Which exact plate combination opens the gate?")]), packet)
        integration.commit_mapping(state, proposal)
        self.assertEqual(state["phase"], "mapping_lead_resolve")
        self.assertFalse(state["issues"][-1]["resolved"])
        audit = dict(verdict="accept",
                     checks={key: True for key in game.AUDIT_CHECKS}, findings=[],
                     reason="The rule now resolves the gate state.")
        before = state["design_version_sha256"]
        integration.accept_resolution(state, state["pending"]["question"],
            dict(content="The gate opens only when all three plates are pressed.",
                 status="settled", reason="The outcome is now specific."),
            audit, node_id=cited["node_id"])
        state["issues"][-1]["resolved"] = True
        integration.restart_inventory_after_mapping_resolution(state)
        self.assertEqual(state["phase"], "inventory")
        self.assertEqual(state["cursor"], 0)
        self.assertEqual(state["decisions"], [])
        self.assertEqual(state["systems"], [])
        self.assertNotEqual(state["design_version_sha256"], before)
        self.assertTrue(state["mapping_enabled"])

    def test_runner_reviews_every_saved_pass_before_completing(self):
        test = IntegrationApiTests("test_incomplete_source_cannot_be_frozen")
        test.setUp()
        self.addCleanup(test.doCleanups)
        studio = test.studios
        state = self.ledger()
        integration.begin_system_mapping(state)
        calls = []
        def answer(jid, system, packet):
            calls.append(packet["item"]["kind"])
            if system.startswith("You are the Systems Integrator."):
                return json.dumps(dict(summary="The cited decisions form a bounded game system.",
                                       issues=[]))
            return json.dumps(dict(verdict="accept",
                checks={key: True for key in game.AUDIT_CHECKS},
                findings=[], reason="The system summary is traceable."))
        studio.infer = answer
        progress = dict(integration=state)
        done = False
        for _ in range(60):
            progress, done = studio.integration_step({"id": "test-mapping"}, progress)
            if done:
                break
        self.assertTrue(done)
        self.assertEqual(state["phase"], "system_map_complete")
        self.assertEqual(len(calls), 2 * len(state["mapping_queue"]))
        self.assertEqual(state["work_orders"], [])


if __name__ == "__main__":
    unittest.main()
