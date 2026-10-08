import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import http_api
import model_engine
import routing
import tool_protocol as protocol
import web_tools_api

TOOL = {"type": "function", "function": {"name": "view_note", "parameters": {"type": "object"}}}
CALL = {"id": "call_first", "type": "function", "function": {"name": "view_note", "arguments": '{"id":"note"}'}}


class NativeToolsTests(unittest.TestCase):
    def test_openai_history_maps_ids_to_ollama_tool_names_without_mutation(self):
        messages = [{"role": "developer", "content": "Keep instructions"}, {"role": "user", "content": "Read note"},
                    {"role": "assistant", "content": None, "tool_calls": [CALL], "reasoning_content": "reason"},
                    {"role": "tool", "tool_call_id": "call_first", "content": "Untrusted note"}]
        old = copy.deepcopy(messages)
        actual = protocol.messages_for_ollama(messages)
        self.assertEqual(messages, old)
        self.assertEqual(actual[0]["role"], "system")
        self.assertEqual(actual[2]["tool_calls"][0]["function"]["arguments"], {"id": "note"})
        self.assertEqual(actual[2]["thinking"], "reason")
        self.assertEqual(actual[-1], {"role": "tool", "tool_name": "view_note", "content": "Untrusted note"})

    def test_out_of_order_parallel_results_are_matched_by_id(self):
        other = {"id": "call_second", "function": {"name": "search_chats", "arguments": {}}}
        messages = [{"role": "assistant", "content": "", "tool_calls": [CALL, other]},
                    {"role": "tool", "tool_call_id": "call_second", "content": "chats"},
                    {"role": "tool", "tool_call_id": "call_first", "content": "note"}]
        result = protocol.messages_for_ollama(messages)
        self.assertEqual([m["tool_name"] for m in result[1:]], ["search_chats", "view_note"])

    def test_unmatched_duplicate_and_missing_results_are_rejected(self):
        assistant = {"role": "assistant", "content": "", "tool_calls": [CALL]}
        result = {"role": "tool", "tool_call_id": "call_first", "content": "note"}
        for messages in ([result], [assistant], [assistant, {"role": "user", "content": "next"}],
                         [assistant, result, result], [dict(assistant, tool_calls=[CALL, CALL]), result]):
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                protocol.messages_for_ollama(messages)

    def test_text_parts_supported_but_image_and_audio_rejected(self):
        actual = protocol.messages_for_ollama([{"role": "user", "content": [{"type": "text", "text": "one"}]}])
        self.assertEqual(actual[0]["content"], "one")
        for kind in ("image_url", "input_audio"):
            with self.assertRaises(ValueError):
                protocol.messages_for_ollama([{"role": "user", "content": [{"type": kind}]}])

    def test_tool_definitions_are_data_not_execution(self):
        body = {"tools": [TOOL]}
        actual = protocol.tools_for_ollama(body)
        actual.clear()
        self.assertEqual(body["tools"], [TOOL])
        self.assertEqual(protocol.tools_for_ollama(dict(body, tool_choice="none")), [])
        for malformed in ({"tools": [TOOL, TOOL]}, {"tools": [None]}, {"tools": [dict(TOOL, type="shell")]},
                          {"tools": [TOOL], "tool_choice": "required"}):
            with self.assertRaises(ValueError):
                protocol.tools_for_ollama(malformed)

    def test_backend_calls_have_unique_ids_and_json_arguments(self):
        message = {"content": "", "tool_calls": [{"function": {"name": "view_note", "arguments": {"id": "note"}}}] * 2}
        result = protocol.assistant_for_openai(message, [TOOL])
        calls = result["tool_calls"]
        self.assertNotEqual(calls[0]["id"], calls[1]["id"])
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"id": "note"})

    def test_unsupplied_backend_tool_and_malformed_calls_fail(self):
        for message in ({"content": "", "tool_calls": [{"function": {"name": "shell", "arguments": {}}}]},
                        {"content": "", "tool_calls": [{"function": {"name": "view_note", "arguments": "bad"}}]},
                        {"content": "", "tool_calls": None}):
            with self.assertRaises(RuntimeError):
                protocol.assistant_for_openai(message, [TOOL])

    def test_reverse_command_requires_explicit_path_and_routes_without_guessing(self):
        body = {"model": "local-ai", "messages": [{"role": "user", "content": "/reverse Inbox/photo.jpg"}]}
        messages, route, prompt = routing.messages_and_route(body)
        self.assertEqual(route, "reverse")
        self.assertEqual(prompt, "Inbox/photo.jpg")
        self.assertEqual(messages[-1]["content"], "/reverse Inbox/photo.jpg")
        with self.assertRaises(ValueError):
            routing.messages_and_route({"model": "local-ai", "messages": [{"role": "user", "content": "/reverse"}]})

    def test_old_commands_do_not_repeat_on_tool_continuation(self):
        body = {"model": "local-ai", "messages": [{"role": "user", "content": "/image old"},
                {"role": "assistant", "content": "", "tool_calls": [CALL]},
                {"role": "tool", "tool_call_id": "call_first", "content": "note"}]}
        self.assertEqual(routing.messages_and_route(body)[1], "text")

    def test_two_inference_requests_resume_with_result_and_preserve_system_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({}, Path(directory))
            try:
                body = {"model": "local-ai", "tools": [TOOL], "messages": [
                    {"role": "system", "content": "Keep this"}, {"role": "user", "content": "Read notes"}]}
                replies = [{"models": []}, {"message": {"content": "", "tool_calls": [
                    {"function": {"name": "view_note", "arguments": {"id": "note"}}}]}},
                    {"models": []}, {"message": {"content": "answer"}}]
                with patch.object(model_engine, "port_open", return_value=False), patch.object(model_engine, "api", side_effect=replies) as api:
                    pending = engine.submit(body).result(2)
                    body["messages"].append(pending)
                    body["messages"].append({"role": "tool", "tool_call_id": pending["tool_calls"][0]["id"], "content": "note result"})
                    self.assertEqual(engine.submit(body).result(2), "answer")
                    self.assertEqual(api.call_args.args[2]["messages"][0]["content"], "Keep this")
                    self.assertEqual(api.call_args.args[2]["messages"][-1]["tool_name"], "view_note")
                    self.assertEqual(len([c for c in api.call_args_list if c.args[1] == "/api/chat"]), 2)
            finally:
                engine.executor.shutdown()

    def test_real_http_stream_and_nonstream_preserve_tool_protocol(self):
        output = protocol.assistant_for_openai({"content": "", "tool_calls": [
            {"function": {"name": "view_note", "arguments": {"id": "note"}}}]}, [TOOL])
        engine = Mock(config={"api_key": "test-key"})
        def submit(body, stream=None):
            import concurrent.futures
            future = concurrent.futures.Future()
            future.set_result(output)
            return future
        engine.submit.side_effect = submit
        server = ThreadingHTTPServer(("127.0.0.1", 0), http_api.Handler)
        server.engine = engine
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for stream in (False, True):
                body = {"model": "local-ai", "stream": stream, "messages": [{"role": "user", "content": "read"}]}
                request = Request(f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                    data=json.dumps(body).encode(), headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"})
                with urlopen(request, timeout=2) as response:
                    text = response.read().decode()
                if stream:
                    chunks = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
                    self.assertEqual(chunks[0]["choices"][0]["delta"]["tool_calls"][0]["index"], 0)
                    self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "tool_calls")
                else:
                    choice = json.loads(text)["choices"][0]
                    self.assertEqual(choice["finish_reason"], "tool_calls")
                    self.assertEqual(choice["message"]["tool_calls"], output["tool_calls"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


class WebBridgeTests(unittest.TestCase):
    def test_specification_exposes_three_vpn_operations(self):
        spec = web_tools_api.specification()
        self.assertEqual({v["post"]["operationId"] for v in spec["paths"].values()}, {"vpn_search_web", "vpn_read_page", "vpn_reverse_image"})
        self.assertEqual(spec["security"], [{"bearerAuth": []}])

    def test_retrieval_uses_existing_vpn_client_and_returns_sources(self):
        config = {"web": {"enabled": True}}
        with patch.object(web_tools_api, "fetch_sources", return_value=[{"url": "https://example.org", "text": "evidence"}]) as fetch:
            result = web_tools_api.execute(config, "vpn_search_web", {"query": "test"})
        fetch.assert_called_once_with(config, "search", {"query": "test"}, text_budget=6000)
        self.assertEqual(result["sources"][0]["text"], "evidence")

    def test_reverse_image_uses_dedicated_fail_closed_client(self):
        config = {"web": {"enabled": True}}
        result = {"matches": [{"page_url": "https://example.org"}]}
        with patch.object(web_tools_api.reverse_image, "search_tool", return_value=result) as search:
            self.assertEqual(web_tools_api.execute(config, "vpn_reverse_image",
                                                   {"workspace_path": "Inbox/photo.jpg"}), result)
        search.assert_called_once_with(config, "Inbox/photo.jpg")

    def test_invalid_arguments_fail_before_network(self):
        with patch.object(web_tools_api, "fetch_sources") as fetch:
            for name, args in (("shell", {}), ("vpn_search_web", {"query": "x", "token": "secret"}),
                               ("vpn_read_page", {"url": "file:///etc/passwd"}),
                               ("vpn_read_page", {"url": "https://user:secret@example.org"}),
                               ("vpn_reverse_image", {"workspace_path": "Inbox/a.jpg", "extra": "x"})):
                with self.assertRaises(ValueError):
                    web_tools_api.execute({}, name, args)
            fetch.assert_not_called()

    def test_missing_configuration_fails_without_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            web_tools_api.execute({}, "vpn_search_web", {"query": "test"})

    def test_real_http_bridge_requires_auth_and_is_absent_from_media_listener(self):
        engine = Mock(config={"api_key": "test-key"})
        for handler in (http_api.Handler, http_api.MediaHandler):
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server.engine = engine
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                request = Request(base + "/tools/openapi.json")
                with self.assertRaises(HTTPError) as error:
                    urlopen(request, timeout=2)
                self.assertEqual(error.exception.code, 401 if handler is http_api.Handler else 404)
                headers = {"Authorization": "Bearer test-key", "Content-Type": "application/json"}
                request = Request(base + "/tools/vpn_search_web", data=b'{"query":"test"}', headers=headers)
                with patch.object(http_api, "retrieve_tool", return_value={"sources": []}) as retrieve:
                    if handler is http_api.Handler:
                        with urlopen(request, timeout=2) as response:
                            self.assertEqual(json.load(response), {"sources": []})
                        retrieve.assert_called_once_with(engine.config, "vpn_search_web", {"query": "test"})
                    else:
                        with self.assertRaises(HTTPError) as error:
                            urlopen(request, timeout=2)
                        self.assertEqual(error.exception.code, 404)
                        retrieve.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)


if __name__ == "__main__":
    unittest.main()

