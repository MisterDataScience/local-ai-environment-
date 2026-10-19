"""Synthetic shared facilities: lifecycle, isolation, receipts and no execution."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import sqlite3
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import village
import village_infrastructure as infra


class FacilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "village"
        self.cx = village.connect(self.root, test_encrypted=True)
        self.addCleanup(self.cx.close)
        self.project = infra.sha("project-one")
        self.other = infra.sha("project-two")
        infra.initialize(self.cx)

    def request(self, operation, payload, *, project=None, actor="captain", request_id=None, revision=1):
        return infra.host(self.cx, self.root, dict(operation=operation, payload=payload,
            project=project or self.project, actor=actor, identity="coder.general", revision=revision,
            task="synthetic-task", request_id=request_id or infra.sha(str(payload) + str(self.cx.total_changes))))

    def contribution(self, **changes):
        return dict(area="workshop", title="Tiny checklist", body="Review two inputs.",
                    kind="checklist", content="Check A. Check B.", evidence=["Synthetic test report: two cases passed."],
                    tags=["review"], **changes)

    def approved(self):
        candidate = self.request("publish", self.contribution())
        infra.owner_decision(self.cx, "workshop", candidate["id"], "approved", candidate["digest"],
                             "owner reviewed synthetic content", revision=1)
        return candidate

    def test_pending_hidden_exact_approval_reuse_across_projects_and_withdrawal(self):
        candidate = self.request("publish", self.contribution())
        self.assertEqual(self.request("browse", dict(area="workshop")), [])
        with self.assertRaises(PermissionError):
            self.request("browse", dict(area="workshop", item_id=candidate["id"]))
        with self.assertRaises(ValueError):
            infra.owner_decision(self.cx, "workshop", candidate["id"], "approved", "0" * 64, "owner", revision=1)
        infra.owner_decision(self.cx, "workshop", candidate["id"], "approved", candidate["digest"], "owner", revision=1)
        item = self.request("browse", dict(area="workshop", item_id=candidate["id"]), project=self.other)
        self.assertEqual(item["content"], "Check A. Check B.")
        self.assertFalse(item["executable"])
        infra.owner_decision(self.cx, "workshop", candidate["id"], "withdrawn", candidate["digest"], "owner", revision=1)
        with self.assertRaises(PermissionError):
            self.request("browse", dict(area="workshop", item_id=candidate["id"]))

    def test_new_revision_needs_new_approval_and_old_approval_cannot_be_replayed(self):
        first = self.approved()
        proposal = self.contribution(); proposal.update(item_id=first["id"], content="Check A, B and C.")
        second = self.request("publish", proposal)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(self.request("browse", dict(area="workshop", item_id=first["id"]))["revision"], 1)
        with self.assertRaises(ValueError):
            infra.owner_decision(self.cx, "workshop", first["id"], "approved", first["digest"], "owner", revision=1)
        infra.owner_decision(self.cx, "workshop", first["id"], "approved", second["digest"], "owner", revision=2)
        self.assertEqual(self.request("browse", dict(area="workshop", item_id=first["id"]))["revision"], 2)
        with self.assertRaises(PermissionError):
            self.request("publish", proposal, project=self.other)

    def test_project_board_is_durable_isolated_and_owner_lifecycle_is_separate(self):
        notice = self.request("publish", dict(area="noticeboard", title="Blocked", body="Need a fabricated sample."))
        suggestion = self.request("publish", dict(area="suggestions", title="Small helper", body="Propose a parser."))
        self.assertEqual(self.request("browse", dict(area="noticeboard"), project=self.other), [])
        with self.assertRaises(PermissionError):
            self.request("browse", dict(area="noticeboard", item_id=notice["id"]), project=self.other)
        with self.assertRaises(ValueError):
            self.request("publish", dict(area="suggestions", title="Forged", body="Do it", state="implemented"))
        with self.assertRaises(PermissionError):
            self.request("approve", dict(id=suggestion["id"]))
        infra.owner_decision(self.cx, "suggestions", suggestion["id"], "accepted", suggestion["digest"], "owner", project=self.project)
        self.assertEqual(self.request("browse", dict(area="suggestions", item_id=suggestion["id"]))["state"], "accepted")
        with self.assertRaises(ValueError):
            infra.owner_decision(self.cx, "suggestions", suggestion["id"], "implemented", suggestion["digest"], "owner", project=self.project)
        # Reopen the actual DB, retaining existing archive and specialist schema.
        self.cx.close(); self.cx = village.connect(self.root, test_encrypted=True)
        self.addCleanup(self.cx.close)
        infra.initialize(self.cx)
        self.assertEqual(len(self.request("browse", dict(area="noticeboard"))), 1)
        self.assertEqual(len(village.status(self.cx)), 5)

    def test_replay_receipt_survives_reopen_and_changed_payload_is_rejected(self):
        req = infra.sha("same native call")
        first = self.request("publish", self.contribution(), request_id=req)
        self.cx.close(); self.cx = village.connect(self.root, test_encrypted=True)
        self.addCleanup(self.cx.close)
        second = self.request("publish", self.contribution(), request_id=req)
        self.assertEqual(first, second)
        altered = self.contribution(); altered["content"] = "Different content"
        with self.assertRaisesRegex(ValueError, "Replay"):
            self.request("publish", altered, request_id=req)
        self.assertEqual(self.cx.execute("SELECT count(*) FROM workshop_items").fetchone()[0], 1)

    def test_practice_freezes_revision_has_inert_files_and_cited_reported_results(self):
        candidate = self.approved()
        case = self.request("prepare", dict(item_id=candidate["id"], brief="Compare two small examples.",
                                            checks="List actual observations.", fixtures={"sample.txt": "two inputs"}))
        workspace = Path(case["workspace"])
        self.assertFalse(case["executed"])
        self.assertEqual((workspace / "candidate.txt").read_text(), "Check A. Check B.")
        self.assertEqual((workspace / "inputs/sample.txt").read_text(), "two inputs")
        self.assertFalse((workspace / "candidate.txt").stat().st_mode & 0o111)
        with self.assertRaises(ValueError):
            self.request("publish", dict(area="practice", title="Claim", body="All passed", item_id=case["id"], state="verified"))
        result = self.request("publish", dict(area="practice", title="Observed comparison", body="Two examples reviewed; no command run.",
                                              item_id=case["id"], state="inconclusive"), actor="coder.general")
        view = self.request("browse", dict(area="practice", item_id=case["id"]))
        self.assertEqual(view["artifact_digest"], candidate["digest"])
        self.assertEqual(view["results"][0]["id"], result["id"])
        self.assertEqual(view["results"][0]["state"], "inconclusive")
        with self.assertRaises(ValueError):
            self.request("publish", dict(area="practice", title="Other project", body="Claim", item_id=case["id"], state="reported_pass"), project=self.other)
        with self.assertRaises(PermissionError):
            self.request("prepare", dict(item_id=candidate["id"], brief="B", checks="C"), actor="coder.general")

    def test_practice_path_and_size_guards_and_no_source_execution(self):
        candidate = self.approved()
        for fixtures in ({"../escape": "no"}, {"/absolute": "no"}, {"a": "x" * 17000}, {"nested/path": "no"}):
            with self.assertRaises(ValueError):
                self.request("prepare", dict(item_id=candidate["id"], brief="B", checks="C", fixtures=fixtures))
        self.assertFalse((Path(self.temp.name) / "escape").exists())
        (self.root / "practice").symlink_to(Path(self.temp.name))
        with self.assertRaises(ValueError):
            self.request("prepare", dict(item_id=candidate["id"], brief="B", checks="C"))

    def test_scope_revision_unknown_fields_and_private_reference_guards(self):
        with self.assertRaises(PermissionError):
            self.request("browse", dict(area="workshop"), revision=2)
        forged = self.contribution(); forged["approval"] = "owner"
        with self.assertRaises(ValueError):
            self.request("publish", forged)
        bad = self.contribution(); bad["evidence"] = ["msg:private-or-guessed"]
        with self.assertRaises(PermissionError):
            self.request("publish", bad)
        with self.cx:
            self.cx.execute("DELETE FROM grants WHERE specialist_id='coder.general'")
        with self.assertRaises(PermissionError):
            self.request("browse", dict(area="workshop"))

    def test_practice_attachment_shares_only_the_case_with_an_explicit_project(self):
        candidate = self.approved()
        case = self.request("prepare", dict(item_id=candidate["id"], brief="B", checks="C"))
        workspace_project = infra.project_key(case["workspace"])
        self.assertEqual(self.request("browse", dict(area="practice", item_id=case["id"]), project=workspace_project)["id"], case["id"])
        self.request("publish", dict(area="noticeboard", title="Project note", body="Keep in original project."))
        self.assertEqual(self.request("browse", dict(area="noticeboard"), project=workspace_project), [])
        source_project = Path(self.temp.name) / "source-project"; source_project.mkdir()
        target = Path(self.temp.name) / "copied-practice"; target.mkdir()
        # Exercise the explicit dispatch, including original-project ownership.
        from argparse import Namespace
        with self.cx:
            self.cx.execute("UPDATE practice_cases SET project=? WHERE id=?", (infra.project_key(source_project), case["id"]))
        args = Namespace(project=source_project, command="practice", action="attach", id=case["id"],
                         target=target, digest=case["digest"], owner_approval="owner approves fabricated case copy")
        self.assertTrue(infra.dispatch(self.cx, self.root, args)["linked"])
        self.assertEqual(self.request("browse", dict(area="practice", item_id=case["id"]), project=infra.project_key(target))["id"], case["id"])

    def test_failed_schema_migration_rolls_back_and_does_not_touch_archive(self):
        root = Path(self.temp.name) / "migration-test"
        cx = village.connect(root, test_encrypted=True)
        self.addCleanup(cx.close)
        cx.set_authorizer(lambda action, arg1, *rest: sqlite3.SQLITE_DENY
                          if action == sqlite3.SQLITE_CREATE_TABLE and arg1 == "practice_cases" else sqlite3.SQLITE_OK)
        with self.assertRaises(sqlite3.DatabaseError):
            infra.initialize(cx)
        cx.set_authorizer(None)
        self.assertFalse(cx.execute("SELECT name FROM sqlite_master WHERE name='facility_schema'").fetchone())
        self.assertEqual(len(village.status(cx)), 5)
        infra.initialize(cx)
        self.assertEqual(cx.execute("SELECT version FROM facility_schema").fetchone()[0], 1)

    def test_revocation_between_preflight_and_mutation_cannot_commit(self):
        original = infra.validate_identity
        calls = []
        def revoke_after_preflight(cx, envelope):
            original(cx, envelope)
            calls.append(True)
            if len(calls) == 1:
                other = village.connect(self.root, test_encrypted=True)
                with other:
                    other.execute("DELETE FROM grants WHERE specialist_id='coder.general'")
                other.close()
        with patch.object(infra, "validate_identity", side_effect=revoke_after_preflight):
            with self.assertRaises(PermissionError):
                self.request("publish", self.contribution())
        self.assertEqual(self.cx.execute("SELECT count(*) FROM workshop_items").fetchone()[0], 0)

    def test_bounded_search_and_inert_malicious_artifact(self):
        malicious = self.contribution()
        sentinel = Path(self.temp.name) / "should-never-exist"
        malicious.update(kind="python", content="from pathlib import Path\nPath(" + repr(str(sentinel)) + ").touch()")
        candidate = self.request("publish", malicious)
        infra.owner_decision(self.cx, "workshop", candidate["id"], "approved", candidate["digest"], "owner inspecting test", revision=1)
        self.request("prepare", dict(item_id=candidate["id"], brief="Review inert code", checks="Do not execute"))
        self.assertFalse(sentinel.exists())
        for index in range(12):
            self.request("publish", dict(area="noticeboard", title="Record " + str(index), body="No background operation."))
        self.assertEqual(len(self.request("browse", dict(area="noticeboard"))), 10)
        self.assertEqual(self.request("browse", dict(area="noticeboard", query="%")), [])
        oversized = self.contribution(); oversized["content"] = "x" * 16001
        with self.assertRaises(ValueError):
            self.request("publish", oversized)

    def test_future_schema_rejected_without_rewriting_it(self):
        with self.cx:
            self.cx.execute("UPDATE facility_schema SET version=999")
        with self.assertRaises(RuntimeError):
            infra.initialize(self.cx)
        self.assertEqual(self.cx.execute("SELECT version FROM facility_schema").fetchone()[0], 999)

    def test_owner_cli_round_trip_uses_actual_parser_and_exact_digest(self):
        project = Path(self.temp.name) / "work-project"; project.mkdir()
        source = project / "checklist.txt"; source.write_text("Review the fabricated input.")
        def cli(*argv):
            output = io.StringIO()
            original = village.connect
            with patch.object(village, "connect", side_effect=lambda root: original(root, test_encrypted=True)), contextlib.redirect_stdout(output):
                village.main(["--root", str(self.root), "workshop", "--project", str(project), *argv])
            return json.loads(output.getvalue())
        candidate = cli("propose", "CLI checklist", "--file", str(source), "--purpose", "Synthetic parser round trip")
        cli("decide", candidate["id"], "approved", "--revision", "1", "--digest", candidate["digest"], "--owner-approval", "owner read exact content")
        self.assertEqual(cli("show", candidate["id"])[0]["content"], "Review the fabricated input.")


if __name__ == "__main__":
    unittest.main()
