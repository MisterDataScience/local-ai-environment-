from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tool_registry as registry
import tool_executor as executor
import tool_loop as loop
import web_client

WEB = {"enabled": True, "url": "http://127.0.0.1:8090", "api_key": "private-token"}


def call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


def reply(calls=None, content=""):
    return {"message": {"role": "assistant", "content": content, "tool_calls": calls or []}}


def payload():
    return {"model": "qwen3:14b", "options": {"num_ctx": 8192}, "messages": [{"role": "user", "content": "Research"}]}


class WebToolTests(unittest.TestCase):
    def test_web_definitions_are_available_only_when_enabled(self):
        self.assertEqual(len(registry.definitions()), 2)
        self.assertEqual({t["function"]["name"] for t in registry.definitions(True)},
                         {"calculate", "get_current_time", "search_web", "read_page"})

    def test_web_arguments_are_strict(self):
        for name, args in (("search_web", {"query": ""}), ("search_web", {"query": "x" * 501}),
                           ("read_page", {"url": "file:///etc/passwd"}), ("read_page", {"url": "http://user:pass@example.org"}),
                           ("read_page", {"url": "https://example.org", "proxy": "elsewhere"})):
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                registry.validate(name, args)

    def test_disabled_or_wrong_endpoint_cannot_launch_worker(self):
        with patch.object(executor.subprocess, "Popen") as launched:
            for web in (None, {"enabled": False}, {"enabled": True, "url": "https://public.example"}):
                result = executor.execute("search_web", {"query": "test"}, web=web)
                self.assertEqual(result["error"]["code"], "web_disabled")
            launched.assert_not_called()

    def test_web_credentials_use_stdin_and_worker_has_longer_bounded_deadline(self):
        worker = Mock(returncode=0)
        worker.poll.return_value = 0
        worker.communicate.return_value = (b'{"ok":true,"result":{"sources":[]}}', b"")
        with patch.object(executor.subprocess, "Popen", return_value=worker) as launched:
            executor.execute("search_web", {"query": "test"}, timeout=9999, web=WEB)
        self.assertNotIn("private-token", str(launched.call_args))
        request = json.loads(worker.communicate.call_args.args[0])
        self.assertEqual(request["web"]["api_key"], "private-token")
        self.assertEqual(worker.communicate.call_args.kwargs["timeout"], 140)

    def test_multiple_web_calls_have_stable_source_numbers_without_credentials(self):
        api = Mock(side_effect=[reply([call("search_web", {"query": "test"})]),
                              reply([call("read_page", {"url": "https://example.org/b"})]), reply(content="Evidence [1], [2]")])
        results = [{"ok": True, "result": {"sources": [{"url": "https://example.org/a", "kind": "search snippet", "text": "snippet"}]}},
                   {"ok": True, "result": {"sources": [{"url": "https://example.org/b", "kind": "page text", "text": "page", "truncated": True}]}}]
        with patch.object(loop, "execute", side_effect=results) as execute:
            answer = loop.run_chat(api, "local", payload(), web=WEB)
        self.assertIn("[1](https://example.org/a)", answer)
        self.assertIn("[2](https://example.org/b)", answer)
        self.assertIn("truncated", answer)
        self.assertEqual(execute.call_args.kwargs["web"], WEB)
        for request in api.call_args_list:
            self.assertNotIn("private-token", json.dumps(request.args[2]))
        tool_messages = [m for m in api.call_args.args[2]["messages"] if m["role"] == "tool"]
        self.assertEqual([json.loads(m["content"])["result"]["sources"][0]["source_id"] for m in tool_messages], [1, 2])

    def test_vpn_failure_produces_no_source_links(self):
        api = Mock(side_effect=[reply([call("search_web", {"query": "test"})]), reply(content="Search unavailable")])
        with patch.object(loop, "execute", return_value={"ok": False, "error": {"message": "VPN unavailable"}}):
            answer = loop.run_chat(api, "local", payload(), web=WEB)
        self.assertNotIn("Sources:", answer)
        self.assertIn("VPN unavailable", api.call_args.args[2]["messages"][-1]["content"])

    def test_loop_does_not_advertise_unconfigured_web_tools(self):
        api = Mock(return_value=reply(content="offline"))
        loop.run_chat(api, "local", payload())
        self.assertEqual(len(api.call_args.args[2]["tools"]), 2)

    def test_loopback_api_redirects_are_not_followed(self):
        self.assertIsNone(web_client.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://public.example"))

    def test_real_worker_calls_only_fake_loopback_service_and_returns_sources(self):
        observed = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                observed.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                data = json.dumps({"sources": [{"url": "https://example.org/article", "title": "Article", "kind": "page text", "text": "Evidence " * 500}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 8090), Handler)
        except OSError:
            self.skipTest("Fixed retrieval port is occupied")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = executor.execute("read_page", {"url": "https://example.org/article"}, web=WEB)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["result"]["sources"][0]["url"], "https://example.org/article")
            self.assertTrue(result["result"]["sources"][0]["truncated"])
            self.assertLessEqual(len(json.dumps(result).encode()), 4096)
            self.assertNotIn("private-token", json.dumps(result))
            self.assertEqual(observed, [("/read", "Bearer private-token", {"url": "https://example.org/article"})])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
