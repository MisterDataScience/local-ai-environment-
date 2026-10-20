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

    def test_ready_order_launches_approved_role_in_isolated_project(self):
        project=self.studios.store.ingest(self.institution,'Base game',
            [('main.c',b'int main_value = 1;')],dict(kind='fixture'))['project']
        staff=self.studios.store.prepare_staff(self.institution)
        engine_proposal=staff[1]
        approved=self.studios.store.preview(engine_proposal['id'])
        resident=self.studios.store.review(engine_proposal['id'],approved['review_digest'],'approve')['resident']
        order=dict(id='WO-0001',title='Implement gate rule',kind='code',status='planned',depends_on=[],
            responsible_role='Gameplay programmer',decision_ids=['G0.1:D1'],inputs=['Approved rule'],
            outputs=['Updated game code'],prerequisite_decision_ids=[],done_when='The gate follows the reviewed rule.',
            check={'method':'automated_test','procedure':'Run the gate rule tests for edge cases.',
                   'expected_result':'The observed result matches the design.'},evidence=['Test log'])
        state=dict(phase='work_order_complete',work_order_gate={'passed':True},work_orders=[order])
        job='studio-job:test-dispatch'
        with self.studios.store.db() as cx,cx:
            cx.execute('INSERT INTO studio_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (job,self.institution,'','integration','complete','{}',encoded({'integration':state}),0,0,0,'',1))
        self.studios.infer=lambda jid,system,packet:json.dumps({'action':'done','args':{'summary':'Finished isolated implementation.'},'note':'Work order complete.'})
        result=self.studios.execute({'operation':'dispatch_work_orders','institution':self.institution,
            'job':job,'project':project,'limit':1})
        self.assertEqual(len(result['started']),1)
        launched=result['started'][0]
        self.assertEqual(launched['role'],'Gameplay programmer')
        self.assertNotEqual(launched['project'],project)
        with self.studios.store.db() as cx:
            branch=cx.execute('SELECT project FROM studio_jobs WHERE id=?',(launched['job'],)).fetchone()[0]
        self.assertEqual(branch,launched['project'])
        with self.studios.store.db() as cx:
            self.assertEqual(self.studios.store.project(cx,branch,self.institution)['state'],'active')
        self.assertTrue(any(row['path']=='.studio-work-order.json' for row in self.studios.store.tree(branch)))
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            with self.studios.store.db() as cx:
                session_state=cx.execute('SELECT state FROM studio_jobs WHERE id=?',(launched['job'],)).fetchone()[0]
            if session_state=='complete':break
            time.sleep(.01)
        self.assertEqual(session_state,'complete')
        original=self.studios.store.read(branch,'main.c')['sha256']
        self.studios.store.edit(branch,'main.c','int main_value = 2;',original)
        self.assertEqual(self.studios.store.read(project,'main.c')['text'],'int main_value = 1;')
        self.studios.execute({'operation':'report_work_order','institution':self.institution,'job':job,
            'work_order':'WO-0001','result':'Implemented the gate rule and verified the expected behaviour.',
            'evidence':['Automated test output: all cases passed'],'check_status':'passed'})
        self.studios.execute({'operation':'review_work_order','institution':self.institution,'job':job,
            'work_order':'WO-0001','decision':'accept','notes':'Reviewed the isolated change and evidence.'})
        self.assertEqual(self.studios.store.read(project,'main.c')['text'],'int main_value = 2;')

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
        while state["mapping_queue"] and state["mapping_queue"][0]["kind"] == "group":
            packet = integration.mapping_packet(state)
            names = {"G0": "Gate Mechanics", "G0.1": "Gate Mechanics",
                     "G0.2": "Gate Control", "G0.3": "Player Feedback",
                     "G0.4": "Level Flow", "G0.5": "Puzzle Rules"}
            groups = {}
            for decision in packet["decisions"]:
                name = names[decision["node_id"]]
                groups.setdefault(name, []).append(decision["id"])
            proposals = []
            for name, ids in groups.items():
                known = next((s for s in packet["known_systems"] if s["name"] == name), None)
                proposals.append(dict(id=known["id"] if known else "", name=name,
                    decision_ids=ids, summary="A coherent set of rules controls " + name + "."))
            result = integration.mapping_result(dict(systems=proposals, issues=[]), packet)
            integration.commit_mapping(state, result)
            state["phase"] = "system_mapping" if state["mapping_cursor"] < len(state["mapping_queue"]) else state["phase"]
        self.assertEqual(len(state["systems"]), 5)
        self.assertEqual({d for system in state["systems"] for d in system["decision_ids"]},
                         {row["id"] for row in state["decisions"]})
        gate = next(system for system in state["systems"] if system["name"] == "Gate Mechanics")
        self.assertEqual(len(gate["decision_ids"]), 2)
        self.assertNotEqual(
            next(system["id"] for system in state["systems"]
                 if "G0.4:D1" in system["decision_ids"]),
            next(system["id"] for system in state["systems"]
                 if "G0.5:D1" in system["decision_ids"]))
        self.assertIn(dict(**{"from": gate["id"], "to": "system:gate-control"},
                           prerequisite_node="G0.1", dependent_node="G0.2"),
                      state["system_links"])
        self.assertEqual(integration.systems_page(state, 0, 2)["next_offset"], 2)
        detail = integration.systems_page(state, system_id=gate["id"], limit=1)
        self.assertEqual(detail["decision_total"], 2)
        self.assertIsNotNone(detail["next_decision_offset"])
        self.assertEqual(state["work_orders"], [])
        self.assertEqual(state["phase"], "system_mapping")


class WorkOrderPlanningTests(unittest.TestCase):
    def mapped(self):
        state = SystemMappingTests.ledger(None)
        ids = [row["id"] for row in state["decisions"]]
        system = {"id": "system:gate-game", "name": "Gate game", "summary": "Rules for the gate game.",
                  "decision_ids": ids}
        state["systems"] = [system]
        for row in state["decisions"]:
            row["system_id"] = system["id"]
        state["phase"] = "system_map_complete"
        state["status"] = "awaiting_work_orders"
        return state

    def task_for(self, decision, packet):
        prerequisite_ids = {row["id"] for row in packet["prerequisite_decisions"]}
        matching = next((node for node in packet["decisions"]
                         if node["id"] == decision["id"]), None)
        # The fixture has one explicit dependency: G0.2 depends on G0.1.
        prerequisite_rows = {row["id"]: row for row in packet["prerequisite_decisions"]}
        deps = [key for key in prerequisite_ids if key == "G0.1:D1" and
                prerequisite_rows[key]["status"] != "deferred"] if matching and matching["node_id"] == "G0.2" else []
        method = "experiment" if decision["status"] == "hypothesis" else "automated_test"
        return {"title": "Implement " + decision["node_id"], "kind": "code",
                "decision_ids": [decision["id"]], "inputs": ["Approved rule " + decision["id"]],
                "outputs": ["Game implementation for " + decision["id"]],
                "prerequisite_decision_ids": deps, "responsible_role": "Gameplay programmer",
                "done_when": "The output follows the cited rule and the stated checks pass.",
                "check": {"method": method, "procedure": "Run the check for the cited rule and its edge cases.",
                          "expected_result": "The observed result matches the expected design rule."},
                "evidence": ["Save the test result and relevant output"]}

    def proposal(self, packet):
        tasks, deferred = [], []
        prerequisite_rows = {row["id"]: row for row in packet["prerequisite_decisions"]}
        for decision in packet["decisions"]:
            blocked = decision["status"] == "deferred" or (
                decision["node_id"] == "G0.2" and any(
                    prerequisite_rows[key]["status"] == "deferred"
                    for key in prerequisite_rows if key == "G0.1:D1"))
            if blocked:
                deferred.append({"decision_id": decision["id"], "reason": "The approved design or a prerequisite defers this implementation."})
            else:
                tasks.append(self.task_for(decision, packet))
        return {"work_orders": tasks, "deferred": deferred, "issues": []}

    def test_work_orders_require_accepted_system_map(self):
        state = self.mapped()
        state["phase"] = "inventory_complete"
        with self.assertRaises(ValueError):
            integration.begin_work_order_planning(state)
        state["phase"] = "system_map_complete"
        integration.begin_work_order_planning(state)
        self.assertEqual(state["phase"], "work_order_planning")
        self.assertEqual(state["work_order_queue"][0], {"system": "system:gate-game", "offset": 0})

    def test_planning_covers_decisions_and_derives_task_dependencies(self):
        state = self.mapped()
        integration.begin_work_order_planning(state)
        while state["phase"] == "work_order_planning":
            packet = integration.work_order_packet(state)
            result = integration.work_order_result(self.proposal(packet), packet)
            integration.commit_work_order_pass(state, result)
        self.assertEqual(state["phase"], "work_order_complete")
        self.assertTrue(state["work_order_gate"]["passed"])
        self.assertEqual(len(state["work_orders"]), len(state["decisions"]))
        dependant = next(order for order in state["work_orders"] if "G0.2:D1" in order["decision_ids"])
        prerequisite = next(order for order in state["work_orders"] if "G0.1:D1" in order["decision_ids"])
        self.assertEqual(dependant["depends_on"], [prerequisite["id"]])
        self.assertEqual(dependant["check_status"], "planned")
        page = integration.work_orders_page(state, 0, 2)
        self.assertEqual(page["total"], len(state["decisions"]))
        self.assertEqual(page["next_offset"], 2)

    def test_dispatch_respects_cap_and_owner_review_gates_dependents(self):
        state = self.mapped()
        integration.begin_work_order_planning(state)
        while state["phase"] == "work_order_planning":
            packet = integration.work_order_packet(state)
            integration.commit_work_order_pass(
                state, integration.work_order_result(self.proposal(packet), packet))
        with self.assertRaises(ValueError):
            integration.dispatch_work_orders(state, 5)
        first = integration.dispatch_work_orders(state, 4)
        self.assertEqual(first["running"], 4)
        self.assertEqual(len(first["claimed"]), 4)
        order = next(row for row in state["work_orders"] if row["depends_on"])
        parent = next(row for row in state["work_orders"] if row["id"] in order["depends_on"])
        self.assertEqual(parent["status"], "running")
        self.assertNotEqual(order["status"], "running")
        with self.assertRaises(ValueError):
            integration.report_work_order(state, parent["id"], "done", ["test log"], "passed")
        integration.report_work_order(state, parent["id"],
            "Implementation follows the approved rule and passes its check.",
            ["automated test output: all cases passed"], "passed")
        self.assertEqual(parent["status"], "review")
        self.assertNotEqual(order["status"], "running")
        integration.review_work_order(state, parent["id"], "accept", "Evidence reviewed.")
        self.assertEqual(parent["status"], "done")
        self.assertIn(order, integration.dispatch_work_orders(state, 4)["claimed"])

    def test_failed_check_cannot_be_accepted_or_unlock_dependents(self):
        state = self.mapped()
        integration.begin_work_order_planning(state)
        while state["phase"] == "work_order_planning":
            packet = integration.work_order_packet(state)
            integration.commit_work_order_pass(
                state, integration.work_order_result(self.proposal(packet), packet))
        order = integration.dispatch_work_orders(state, 1)["claimed"][0]
        integration.report_work_order(state, order["id"],
            "Implementation attempt failed the check.", ["failure output"], "failed")
        with self.assertRaises(ValueError):
            integration.review_work_order(state, order["id"], "accept")
        self.assertEqual(order["status"], "review")

    def test_hypothesis_requires_a_planned_experiment(self):
        state = self.mapped()
        state["decisions"][1]["status"] = "hypothesis"
        integration.begin_work_order_planning(state)
        packet = integration.work_order_packet(state)
        proposal = self.proposal(packet)
        proposal["work_orders"][1]["check"]["method"] = "automated_test"
        with self.assertRaises(ValueError):
            integration.work_order_result(proposal, packet)
        proposal["work_orders"][1]["check"]["method"] = "experiment"
        self.assertEqual(len(integration.work_order_result(proposal, packet)["work_orders"]), 4)

    def test_planner_cannot_drop_a_required_prerequisite(self):
        state = self.mapped()
        integration.begin_work_order_planning(state)
        packet = integration.work_order_packet(state)
        proposal = self.proposal(packet)
        dependent = next(task for task in proposal["work_orders"] if task["decision_ids"] == ["G0.2:D1"])
        dependent["prerequisite_decision_ids"] = []
        with self.assertRaises(ValueError):
            integration.work_order_result(proposal, packet)

    def test_deferred_decision_is_explicitly_covered_without_a_task(self):
        state = self.mapped()
        state["decisions"][1]["status"] = "deferred"
        integration.begin_work_order_planning(state)
        packet = integration.work_order_packet(state)
        result = integration.work_order_result(self.proposal(packet), packet)
        self.assertEqual({row["decision_id"] for row in result["deferred"]},
                         {"G0.1:D1", "G0.2:D1"})
        self.assertNotIn("G0.1:D1", [key for task in result["work_orders"] for key in task["decision_ids"]])

    def test_settled_decision_cannot_be_arbitrarily_deferred(self):
        state = self.mapped()
        integration.begin_work_order_planning(state)
        packet = integration.work_order_packet(state)
        proposal = self.proposal(packet)
        proposal["work_orders"] = [task for task in proposal["work_orders"]
                                   if "G0.3:D1" not in task["decision_ids"]]
        proposal["deferred"].append({"decision_id": "G0.3:D1",
                                     "reason": "The planner would prefer to postpone this work."})
        with self.assertRaises(ValueError):
            integration.work_order_result(proposal, packet)

    def test_missing_rule_returns_before_work_orders_are_created(self):
        state = self.mapped()
        integration.begin_work_order_planning(state)
        packet = integration.work_order_packet(state)
        issue = {"node_id": "G0.2", "decision_ids": ["G0.2:D1"],
                 "question": "Which plate combination opens the gate?"}
        result = integration.work_order_result({"work_orders": [], "deferred": [], "issues": [issue]}, packet)
        integration.commit_work_order_pass(state, result)
        self.assertEqual(state["phase"], "work_order_lead_resolve")
        self.assertEqual(state["work_orders"], [])
        self.assertEqual(state["pending"]["question"], issue["question"])

    def test_accepted_lead_resolution_invalidates_plan_and_restarts_review_chain(self):
        state = self.mapped()
        integration.begin_work_order_planning(state)
        packet = integration.work_order_packet(state)
        issue = {"node_id": "G0.2", "decision_ids": ["G0.2:D1"],
                 "question": "Which plate combination opens the gate?"}
        result = integration.work_order_result({"work_orders": [], "deferred": [], "issues": [issue]}, packet)
        integration.commit_work_order_pass(state, result)
        review = dict(verdict="accept", checks={key: True for key in game.AUDIT_CHECKS},
                      findings=[], reason="The design resolution is specific and traceable.")
        before = state["design_version_sha256"]
        integration.accept_resolution(state, issue["question"],
            {"content": "The gate opens only when all three plates are pressed.",
             "status": "settled", "reason": "This defines the missing gate outcome."},
            review, node_id=issue["node_id"])
        state["issues"][-1]["resolved"] = True
        integration.restart_inventory_after_mapping_resolution(state)
        self.assertEqual(state["phase"], "inventory")
        self.assertEqual(state["work_orders"], [])
        self.assertTrue(state["mapping_enabled"])
        self.assertTrue(state["work_orders_enabled"])
        self.assertNotEqual(state["design_version_sha256"], before)

    def test_host_gate_rejects_dependency_cycles_and_missing_coverage(self):
        state = self.mapped()
        state["work_orders"] = [
            {"id": "WO-0001", "decision_ids": ["G0:D1"], "prerequisite_decision_ids": ["G0.1:D1"], "depends_on": []},
            {"id": "WO-0002", "decision_ids": ["G0.1:D1"], "prerequisite_decision_ids": ["G0:D1"], "depends_on": []},
        ]
        gate = integration.validate_work_orders(state)
        self.assertFalse(gate["passed"])
        self.assertTrue(any("cycle" in error for error in gate["errors"]))
        state["work_orders"] = []
        self.assertFalse(integration.validate_work_orders(state)["passed"])

    def test_runner_saves_planner_and_auditor_as_separate_turns(self):
        fixture = IntegrationApiTests("test_incomplete_source_cannot_be_frozen")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        studio = fixture.studios
        state = self.mapped()
        integration.begin_work_order_planning(state)
        calls = []
        def answer(jid, system, packet):
            if system.startswith("You are the Production Planner."):
                calls.append("planner")
                return json.dumps(self.proposal(packet))
            calls.append("auditor")
            return json.dumps(dict(verdict="accept",
                checks={key: True for key in game.AUDIT_CHECKS},
                findings=[], reason="Every task is traceable and checkable."))
        studio.infer = answer
        progress = {"integration": state}
        done = False
        for _ in range(20):
            progress, done = studio.integration_step({"id": "test-work-orders"}, progress)
            if done:
                break
        self.assertTrue(done)
        self.assertEqual(state["phase"], "work_order_complete")
        self.assertEqual(calls.count("planner"), 2)
        self.assertEqual(calls.count("auditor"), 2)


class SystemMappingContinuationTests(unittest.TestCase):
    ledger = SystemMappingTests.ledger

    def test_mapping_rejects_uncited_or_unrelated_lead_question(self):
        state = self.ledger()
        integration.begin_system_mapping(state)
        packet = integration.mapping_packet(state)
        result = dict(systems=[dict(id="", name="Gate Mechanics",
                          decision_ids=[d["id"] for d in packet["decisions"]],
                          summary="The gate contains an explicit player-facing rule.")],
                      issues=[dict(node_id="G0.2", decision_ids=["missing"],
                                   question="Which plate combination opens the gate?")])
        with self.assertRaises(ValueError):
            integration.mapping_result(result, packet)
        result["issues"][0]["decision_ids"] = [packet["decisions"][0]["id"]]
        with self.assertRaises(ValueError):
            integration.mapping_result(result, packet)

    def test_grouping_requires_exactly_one_system_for_each_decision(self):
        state = self.ledger()
        integration.begin_system_mapping(state)
        packet = integration.mapping_packet(state)
        ids = [row["id"] for row in packet["decisions"]]
        malformed = dict(systems=[dict(id="", name="Gate Mechanics",
            decision_ids=ids[:-1], summary="A coherent system for the supplied gate rules.")],
            issues=[])
        with self.assertRaises(ValueError):
            integration.mapping_result(malformed, packet)
        malformed["systems"][0]["decision_ids"] = ids + [ids[0]]
        with self.assertRaises(ValueError):
            integration.mapping_result(malformed, packet)

    def test_audited_gap_returns_to_lead_then_invalidates_old_map(self):
        state = self.ledger()
        integration.begin_system_mapping(state)
        packet = integration.mapping_packet(state)
        cited = packet["decisions"][0]
        proposal = integration.mapping_result(dict(
            systems=[dict(id="", name="Gate Mechanics",
                          decision_ids=[d["id"] for d in packet["decisions"]],
                          summary="The gate state depends on a rule not yet specified.")],
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
                if packet["item"]["kind"] == "group":
                    groups = []
                    for decision in packet["decisions"]:
                        name = "Subsystem " + decision["node_id"]
                        known = next((s for s in packet["known_systems"]
                                      if s["name"] == name), None)
                        groups.append(dict(id=known["id"] if known else "", name=name,
                            decision_ids=[decision["id"]],
                            summary="The cited rule belongs to " + name + "."))
                    return json.dumps(dict(systems=groups, issues=[]))
                return json.dumps(dict(summary="The systems interact without a missing rule.",
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
        self.assertEqual(len(calls), 34)
        self.assertEqual(len(state["system_interactions"]), 15)
        self.assertEqual(state["work_orders"], [])


if __name__ == "__main__":
    unittest.main()

