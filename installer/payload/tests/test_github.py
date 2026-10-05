import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from github_adapter import GitHubAdapter, definitions
from github_mcp import OfficialMCPTransport
import tool_loop

SHA = "a" * 40
ARGS = {"repository": "owner/project", "branch": "main", "path": "notes.txt"}
CHANGE = dict(ARGS, content="replacement\n", message="Update notes")


def response(sha=SHA, content="old\n"):
    return {"content": [{"type": "text", "text": f"successfully downloaded text file (SHA: {sha})"},
                        {"type": "resource", "resource": {"uri": "repo://owner/project/refs/heads/main/contents/notes.txt", "text": content}}]}


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock(return_value=response())
        self.adapter = GitHubAdapter(self.transport, {"owner/project": ["main"]}, enabled=True)

    def propose(self):
        result = self.adapter.execute("github_propose_file_change", CHANGE)
        self.assertTrue(result["ok"], result)
        return result["result"]

    def test_disabled_never_contacts_server(self):
        adapter = GitHubAdapter(self.transport, {}, enabled=False)
        self.assertFalse(adapter.execute("github_read_file", ARGS)["ok"])
        self.transport.assert_not_called()

    def test_repository_branch_and_path_restrictions(self):
        for delta in ({"repository": "other/private"}, {"branch": "dev"}, {"path": "../token"},
                      {"path": "/etc/passwd"}, {"path": "a//b"}, {"path": "a\\b"}, {"token": "secret"}):
            self.assertFalse(self.adapter.execute("github_read_file", dict(ARGS, **delta))["ok"])
        self.transport.assert_not_called()

    def test_only_two_model_tools_no_commit_or_approval(self):
        self.assertEqual({t["function"]["name"] for t in definitions()},
                         {"github_read_file", "github_propose_file_change"})
        self.assertFalse(self.adapter.execute("approve_and_commit", CHANGE)["ok"])

    def test_read_calls_exact_ref_and_returns_bounded_content(self):
        self.transport.return_value = response(content="x" * 5000)
        result = self.adapter.execute("github_read_file", ARGS)
        self.assertTrue(result["result"]["truncated"])
        self.assertEqual(len(result["result"]["content"]), 2500)
        self.transport.assert_called_once_with("get_file_contents", {"owner": "owner", "repo": "project",
            "path": "notes.txt", "ref": "refs/heads/main"}, timeout=30)

    def test_unsupported_missing_directory_link_and_binary_fail_closed(self):
        for value in ({"content": None}, {"content": [None]}, {"isError": True, "content": []}, {"content": [{"type": "resource_link", "uri": "https://example.org"}]},
                      {"content": [{"type": "text", "text": "[]"}]},
                      {"content": [{"type": "text", "text": f"successfully downloaded text file (SHA: {SHA})"},
                                   {"type": "resource", "resource": {"blob": "YWJj"}}]}):
            self.transport.return_value = value
            self.assertFalse(self.adapter.execute("github_propose_file_change", CHANGE)["ok"])
        self.assertEqual(self.adapter._pending, {})

    def test_default_branch_fallback_and_symlink_notes_rejected(self):
        for note in (" Note: the provided ref does not exist", " Dereferenced symlink"):
            value = response()
            value["content"][0]["text"] += note
            self.transport.return_value = value
            self.assertFalse(self.adapter.execute("github_read_file", ARGS)["ok"])

    def test_different_resource_path_repo_or_branch_rejected(self):
        for uri in ("repo://owner/other/refs/heads/main/contents/notes.txt",
                    "repo://owner/project/refs/heads/main/contents/other.txt",
                    "repo://owner/project/refs/heads/dev/contents/notes.txt"):
            value = response()
            value["content"][1]["resource"]["uri"] = uri
            self.transport.return_value = value
            self.assertFalse(self.adapter.execute("github_read_file", ARGS)["ok"])

    def test_resolved_commit_resource_is_accepted(self):
        value = response()
        value["content"][1]["resource"]["uri"] = "repo://owner/project/sha/" + "b" * 40 + "/contents/notes.txt"
        self.transport.return_value = value
        self.assertTrue(self.adapter.execute("github_read_file", ARGS)["ok"])

    def test_proposal_does_not_write_and_review_is_exact_copy(self):
        proposal = self.propose()
        reviewed = self.adapter.review(proposal["proposal_id"])
        self.assertEqual(reviewed["change"], dict(CHANGE, sha=SHA))
        reviewed["change"]["content"] = "tampered"
        self.assertEqual(self.adapter.review(proposal["proposal_id"])["change"]["content"], CHANGE["content"])
        self.assertEqual([c.args[0] for c in self.transport.call_args_list], ["get_file_contents"])

    def test_exact_approval_commits_plain_text_and_sha_once(self):
        proposal = self.propose()
        self.adapter.approve_and_commit(proposal["proposal_id"], proposal["digest"])
        self.transport.assert_called_with("create_or_update_file", {"owner": "owner", "repo": "project",
            "branch": "main", "path": "notes.txt", "content": "replacement\n", "message": "Update notes", "sha": SHA}, timeout=30)
        with self.assertRaises(KeyError):
            self.adapter.approve_and_commit(proposal["proposal_id"], proposal["digest"])

    def test_mismatched_approval_consumes_proposal_without_network(self):
        proposal = self.propose()
        self.transport.reset_mock()
        with self.assertRaises(ValueError):
            self.adapter.approve_and_commit(proposal["proposal_id"], "wrong")
        self.transport.assert_not_called()

    def test_expiry_blocks_write(self):
        proposal = self.propose()
        self.adapter.clock = lambda: float("inf")
        with self.assertRaises(ValueError):
            self.adapter.approve_and_commit(proposal["proposal_id"], proposal["digest"])
        self.assertEqual(self.transport.call_count, 1)

    def test_stale_sha_blocks_write(self):
        proposal = self.propose()
        self.transport.return_value = response(sha="b" * 40)
        with self.assertRaisesRegex(ValueError, "File changed"):
            self.adapter.approve_and_commit(proposal["proposal_id"], proposal["digest"])
        self.assertEqual(self.transport.call_count, 2)

    def test_policy_rechecked_at_approval(self):
        proposal = self.propose()
        self.adapter.enabled = False
        with self.assertRaises(ValueError):
            self.adapter.approve_and_commit(proposal["proposal_id"], proposal["digest"])
        self.assertEqual(self.transport.call_count, 1)

    def test_failed_uncertain_commit_is_not_retried(self):
        proposal = self.propose()
        self.transport.side_effect = [response(), TimeoutError("token-secret")]
        with self.assertRaisesRegex(RuntimeError, "GitHub operation failed") as caught:
            self.adapter.approve_and_commit(proposal["proposal_id"], proposal["digest"])
        self.assertNotIn("token-secret", str(caught.exception))
        with self.assertRaises(KeyError):
            self.adapter.approve_and_commit(proposal["proposal_id"], proposal["digest"])
        self.assertEqual(self.transport.call_count, 3)

    def test_remote_errors_do_not_echo_secret(self):
        self.transport.side_effect = RuntimeError("Authorization: secret")
        result = self.adapter.execute("github_read_file", ARGS)
        self.assertFalse(result["ok"])
        self.assertNotIn("secret", str(result))

    def test_oversized_change_denied_before_read(self):
        self.assertFalse(self.adapter.execute("github_propose_file_change", dict(CHANGE, content="x" * 4097))["ok"])
        self.transport.assert_not_called()

    def test_transport_does_not_request_credential_for_forbidden_tool(self):
        provider = Mock()
        with self.assertRaises(ValueError):
            OfficialMCPTransport(provider)("delete_repository", {})
        provider.assert_not_called()

    def test_tool_loop_advertises_account_tools_without_web_and_reads(self):
        call = {"function": {"name": "github_read_file", "arguments": ARGS}}
        api = Mock(side_effect=[{"message": {"tool_calls": [call], "content": ""}}, {"message": {"content": "done"}}])
        payload = {"messages": [{"role": "user", "content": "Read notes"}], "options": {"num_ctx": 4096}}
        answer = tool_loop.run_chat(api, "local", payload, github=self.adapter, web={"enabled": True})
        self.assertEqual(answer, "done")
        names = {t["function"]["name"] for t in api.call_args_list[0].args[2]["tools"]}
        self.assertIn("github_read_file", names)
        self.assertNotIn("search_web", names)
        self.assertIn("old", api.call_args_list[1].args[2]["messages"][-1]["content"])

    def test_loop_does_not_allow_model_to_approve_or_send_web(self):
        for name in ("approve_and_commit", "search_web"):
            api = Mock(side_effect=[{"message": {"tool_calls": [{"function": {"name": name, "arguments": {}}}], "content": ""}},
                                    {"message": {"content": "failed"}}])
            payload = {"messages": [], "options": {"num_ctx": 4096}}
            tool_loop.run_chat(api, "local", payload, github=self.adapter, web={"enabled": True})
            self.assertIn('"ok": false', api.call_args_list[1].args[2]["messages"][-1]["content"])
        self.transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
