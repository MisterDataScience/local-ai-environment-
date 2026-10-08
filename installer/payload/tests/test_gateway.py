import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway
import http_api
import model_engine
import routing
import workflows
from text_models import DEFAULT_TEXT_MODELS, configured_text_models
import copy


def request(text):
    return {"model": "local-ai", "messages": [{"role": "user", "content": text}]}


class GatewayTests(unittest.TestCase):
    def test_old_backend_is_rejected_before_any_listener_opens(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.json').write_text('{}')
            with patch.object(gateway, 'ROOT', root), patch.object(gateway, 'api', return_value={'version': '0.39.0'}), patch.object(gateway, 'ThreadingHTTPServer') as server:
                with self.assertRaisesRegex(RuntimeError, '0.40.0'):
                    gateway.main()
                server.assert_not_called()

    def test_engine_returns_tool_call_without_executing_another_round(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({"text_models": DEFAULT_TEXT_MODELS}, Path(directory))
            try:
                call = {"function": {"name": "search_chats", "arguments": {"query": "notes"}}}
                replies = [{"models": []}, {"message": {"role": "assistant", "content": "", "tool_calls": [call]}}]
                body = request("Find notes")
                body["model"] = "local-ai-small"
                body["tools"] = [{"type": "function", "function": {"name": "search_chats", "parameters": {"type": "object"}}}]
                with patch.object(model_engine, "port_open", return_value=False), \
                     patch.object(model_engine, "api", side_effect=replies) as backend:
                    answer = engine.submit(body).result(5)
                self.assertEqual(answer["tool_calls"][0]["function"]["name"], "search_chats")
                self.assertEqual(len([c for c in backend.call_args_list if c.args[1] == "/api/chat"]), 1)
                self.assertEqual(backend.call_args.args[2]["model"], "qwen3:4b")
                self.assertEqual(backend.call_args.args[2]["keep_alive"], 120)
                self.assertEqual(backend.call_args.args[2]["tools"], body["tools"])
                self.assertEqual(engine.state, "idle")
            finally:
                engine.executor.shutdown()

    def test_obsolete_account_activation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                model_engine.Engine({"github": {"enabled": True}}, Path(directory))

    def test_entrypoint_wires_private_listeners_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {"gateway_port": 8001, "remote_access": {"enabled": True}}
            (root / "config.json").write_text(json.dumps(config))
            engine = Mock()
            api_server, media_server = Mock(), Mock()
            api_server.serve_forever.side_effect = KeyboardInterrupt
            with patch.object(gateway, "ROOT", root), patch.object(gateway, "port_open", return_value=False), \
                 patch.object(gateway, "Engine", return_value=engine) as create_engine, \
                 patch.object(gateway, "ThreadingHTTPServer", side_effect=[api_server, media_server]) as server, \
                 patch.object(gateway.signal, "signal"), patch.object(gateway.threading, "Thread"), \
                 patch.object(gateway, "api", return_value={'version': '0.40.0'}), \
                 patch.object(gateway.logging, "basicConfig"):
                gateway.main()
            create_engine.assert_called_once_with(config)
            self.assertEqual(server.call_args_list[0].args, (("127.0.0.1", 8001), http_api.Handler))
            self.assertEqual(server.call_args_list[1].args, (("127.0.0.1", 8002), http_api.MediaHandler))
            self.assertIs(api_server.engine, engine)
            self.assertIs(media_server.engine, engine)
            engine.executor.shutdown.assert_called_once_with(wait=True)
            engine.stop_comfy.assert_called_once()
            api_server.server_close.assert_called_once()
            media_server.shutdown.assert_called_once()
            media_server.server_close.assert_called_once()

    def test_web_routes_retrieve_before_local_text_and_append_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({}, Path(directory))
            try:
                for command in ("/search test", "/read https://example.org Summarise"):
                    with patch.object(model_engine, "port_open", return_value=False), \
                         patch.object(model_engine, "retrieve", return_value=([{"role": "user", "content": "evidence"}], "\nSources")) as retrieve, \
                         patch.object(model_engine, "api", side_effect=[{"models": []}, {"message": {"content": "answer"}}]) as backend:
                        self.assertEqual(engine.submit(request(command)).result(2), "answer\nSources")
                        self.assertEqual(backend.call_args.args[1], "/api/chat")
                        self.assertEqual(backend.call_args.args[2]["messages"][0]["content"], "evidence")
                        self.assertEqual(retrieve.call_args.args[1], command.split()[0][1:])
            finally:
                engine.executor.shutdown()

    def test_web_failure_does_not_hallucinate_answer_or_call_ollama(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({}, Path(directory))
            try:
                with patch.object(model_engine, "port_open", return_value=False), \
                     patch.object(model_engine, "retrieve", side_effect=RuntimeError("VPN unavailable")), \
                     patch.object(model_engine, "api") as backend:
                    with self.assertRaises(RuntimeError):
                        engine.submit(request("/search test")).result(2)
                    backend.assert_not_called()
                    self.assertEqual(engine.state, "idle")
            finally:
                engine.executor.shutdown()

    def test_new_generated_media_uses_private_https_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workflows").mkdir()
            (root / "workflows/image.json").write_text(json.dumps(
                {"1": {"inputs": {"text": "__LOCAL_AI_PROMPT__"}}}))
            comfy = root / "comfy"
            (comfy / "output").mkdir(parents=True)
            (comfy / "output/result.png").write_bytes(b"generated image")
            engine = model_engine.Engine({"comfy_dir": str(comfy), "remote_access": {
                "enabled": True, "media_url": "https://mac.example.ts.net:8443"}}, root)
            try:
                def start():
                    engine.process = Mock()
                    engine.process.poll.return_value = None
                replies = [{"prompt_id": "job"}, {"job": {"status": {"completed": True},
                           "outputs": {"7": {"images": [{"filename": "result.png", "type": "output"}]}}}}]
                with patch.object(engine, "unload_ollama"), patch.object(engine, "start_comfy", side_effect=start), \
                     patch.object(engine, "stop_comfy"), patch.object(model_engine, "api", side_effect=replies):
                    result = engine.render("image", "a car")
                self.assertIn("https://mac.example.ts.net:8443/media/", result)
                self.assertNotIn("127.0.0.1", result)
                self.assertEqual(next((root / "media").iterdir()).read_bytes(), b"generated image")
            finally:
                engine.executor.shutdown()

    def test_media_listener_exposes_files_but_not_chat_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = model_engine.Engine({}, root)
            (root / "media/test.png").write_bytes(b"test image")
            server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), http_api.MediaHandler)
            server.engine = engine
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/media/test.png") as response:
                    self.assertEqual(response.read(), b"test image")
                    self.assertEqual(response.headers["Content-Type"], "image/png")
                for path in ("/health", "/v1/models", "/media/../config.json"):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(base + path)
                    self.assertEqual(error.exception.code, 404)
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/v1/chat/completions", data=b"{}"))
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                engine.executor.shutdown()

    def test_text_presets_forward_model_timeout_and_context(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({"text_models": DEFAULT_TEXT_MODELS}, Path(directory))
            try:
                for identifier, preset in DEFAULT_TEXT_MODELS.items():
                    body = request("hello")
                    body.update(model=identifier, keep_alive=-1, options={"num_ctx": 999999})
                    with patch.object(model_engine, "port_open", return_value=False), \
                         patch.object(model_engine, "api", side_effect=[{"models": []},
                             {"message": {"content": "answer"}}]) as api:
                        self.assertEqual(engine.submit(body).result(2), "answer")
                        payload = api.call_args_list[-1].args[2]
                        self.assertEqual(payload["model"], preset["model"])
                        self.assertEqual(payload["keep_alive"], preset["keep_alive_seconds"])
                        self.assertEqual(payload["options"]["num_ctx"], preset["num_ctx"])
                invalid = request("hello")
                invalid["model"] = "qwen3:32b"
                with self.assertRaises(ValueError):
                    engine.submit(invalid)
            finally:
                engine.executor.shutdown()

    def test_text_switch_unloads_before_new_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({"text_models": DEFAULT_TEXT_MODELS}, Path(directory))
            events = []
            def fake_api(base, path, payload=None, timeout=30):
                events.append((path, payload))
                if path == "/api/ps":
                    return {"models": [{"name": "qwen3:14b"}]} if len(events) <= 2 else {"models": []}
                return {"message": {"content": "small answer"}} if path == "/api/chat" else {}
            body = request("hello")
            body["model"] = "local-ai-small"
            try:
                with patch.object(model_engine, "api", side_effect=fake_api), \
                     patch.object(model_engine, "port_open", return_value=False):
                    engine.submit(body).result(2)
                self.assertEqual([path for path, _ in events],
                                 ["/api/ps", "/api/ps", "/api/generate", "/api/ps", "/api/chat"])
                self.assertEqual(events[2][1], {"model": "qwen3:14b", "keep_alive": 0})
                self.assertEqual(events[-1][1]["model"], "qwen3:4b")
            finally:
                engine.executor.shutdown()

    def test_switch_unload_failure_blocks_new_text_model(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({"text_models": DEFAULT_TEXT_MODELS}, Path(directory))
            body = request("hello")
            body["model"] = "local-ai-large"
            try:
                with patch.object(model_engine, "port_open", return_value=False), \
                     patch.object(model_engine, "api", return_value={"models": [{"name": "qwen3:14b"}]}) as api, \
                     patch.object(engine, "unload_ollama", side_effect=RuntimeError("not released")):
                    with self.assertRaises(RuntimeError):
                        engine.submit(body).result(2)
                    self.assertEqual(api.call_count, 1)
            finally:
                engine.executor.shutdown()

    def test_invalid_timeout_settings_are_rejected(self):
        for value in [-1, True, "5m", 3601]:
            presets = copy.deepcopy(DEFAULT_TEXT_MODELS)
            presets["local-ai"]["keep_alive_seconds"] = value
            with self.assertRaises(ValueError):
                configured_text_models({"text_models": presets})
        presets = copy.deepcopy(DEFAULT_TEXT_MODELS)
        presets["local-ai"]["keep_alive_seconds"] = 0
        self.assertEqual(configured_text_models({"text_models": presets})["local-ai"]["keep_alive_seconds"], 0)

    def test_same_loaded_model_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({"text_models": DEFAULT_TEXT_MODELS}, Path(directory))
            engine.text_profile = ('qwen3:14b', 16384, False)
            try:
                with patch.object(model_engine, "port_open", return_value=False), \
                     patch.object(engine, "unload_ollama") as unload, \
                     patch.object(model_engine, "api", side_effect=[{"models": [{"name": "qwen3:14b"}]},
                         {"message": {"content": "answer"}}]):
                    engine.submit(request("hello")).result(2)
                    unload.assert_not_called()
            finally:
                engine.executor.shutdown()

    def test_http_model_list_does_not_load_models_and_echoes_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({"api_key": "test-key", "text_models": DEFAULT_TEXT_MODELS}, Path(directory))
            server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), http_api.Handler)
            server.engine = engine
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            headers = {"Authorization": "Bearer test-key", "Content-Type": "application/json"}
            try:
                with patch.object(model_engine, "api") as backend:
                    with urlopen(Request(base + "/v1/models", headers=headers)) as response:
                        self.assertEqual({m["id"] for m in json.load(response)["data"]}, set(DEFAULT_TEXT_MODELS))
                    backend.assert_not_called()
                body = request("hello")
                body["model"] = "local-ai-small"
                def streaming(base, payload, sink):
                    sink.send({'content': 'small answer'})
                    return {'message': {'content': 'small answer'}}
                with patch.object(model_engine, "port_open", return_value=False), \
                     patch.object(model_engine.token_stream, 'chat', side_effect=streaming), \
                     patch.object(model_engine, "api", side_effect=lambda base, path, payload=None, timeout=30:
                         {"models": []} if path == "/api/ps" else {"message": {"content": "small answer"}}):
                    for stream in (False, True):
                        body["stream"] = stream
                        with urlopen(Request(base + "/v1/chat/completions", headers=headers,
                                             data=json.dumps(body).encode())) as response:
                            content = response.read().decode()
                        self.assertIn('"model": "local-ai-small"', content)
                        self.assertIn("small answer", content)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                engine.executor.shutdown()

    def test_commands_route_only_on_latest_user_message(self):
        body = request("Explain what /video does")
        self.assertEqual(routing.messages_and_route(body)[1], "text")
        body["messages"].insert(0, {"role": "user", "content": "/image old request"})
        self.assertEqual(routing.messages_and_route(body)[1], "text")
        self.assertEqual(routing.messages_and_route(request("/VIDEO\nA cat walks"))[1:],
                         ("video", "A cat walks"))

    def test_empty_command_and_unsupported_attachments_fail(self):
        with self.assertRaises(ValueError):
            routing.messages_and_route([])
        with self.assertRaises(ValueError):
            routing.messages_and_route(request("/image"))
        body = request("text")
        body["messages"][0]["content"] = [{"type": "image_url"}]
        with self.assertRaises(ValueError):
            routing.messages_and_route(body)

    def test_template_does_not_mutate_and_seeds_agree(self):
        template = {"1": {"inputs": {"text": "__LOCAL_AI_PROMPT__", "seed": 0}},
                    "2": {"inputs": {"noise_seed": 0}}}
        output = workflows.fill_workflow(template, "a landscape")
        self.assertEqual(template["1"]["inputs"]["text"], "__LOCAL_AI_PROMPT__")
        self.assertEqual(output["1"]["inputs"]["text"], "a landscape")
        self.assertEqual(output["1"]["inputs"]["seed"], output["2"]["inputs"]["noise_seed"])

    def test_unload_all_models_then_poll_for_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({}, Path(directory))
            events = []
            replies = iter([{"models": [{"name": "one"}, {"name": "two"}]}, {"models": []}])
            def fake_api(base, path, payload=None, timeout=30):
                events.append((path, payload))
                return next(replies) if path == "/api/ps" else {}
            with patch.object(model_engine, "api", side_effect=fake_api):
                engine.unload_ollama()
            self.assertEqual([event[0] for event in events],
                             ["/api/ps", "/api/generate", "/api/generate", "/api/ps"])
            self.assertTrue(all(event[1]["keep_alive"] == 0 for event in events[1:3]))
            engine.executor.shutdown()

    def test_http_authentication_and_stream_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({"api_key": "test-key"}, Path(directory))
            server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), http_api.Handler)
            server.engine = engine
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + "/v1/models")
                self.assertEqual(error.exception.code, 401)
                headers = {"Authorization": "Bearer test-key", "Content-Type": "application/json"}
                with urlopen(Request(base + "/v1/models", headers=headers)) as response:
                    self.assertEqual(json.load(response)["data"][0]["id"], "local-ai")
                body = request("hello")
                body["stream"] = True
                future = concurrent.futures.Future()
                future.set_result("a completed answer")
                with patch.object(engine, "submit", return_value=future):
                    with urlopen(Request(base + "/v1/chat/completions",
                                         data=json.dumps(body).encode(), headers=headers)) as response:
                        content = response.read().decode()
                        self.assertIn('"content": "a completed answer"', content)
                        self.assertIn("data: [DONE]", content)
                with self.assertRaises(HTTPError):
                    urlopen(base + "/media/../config.json")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                engine.executor.shutdown()

    def test_render_failure_still_stops_comfy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workflows").mkdir()
            (root / "workflows/image.json").write_text(json.dumps(
                {"1": {"inputs": {"text": "__LOCAL_AI_PROMPT__"}}}))
            engine = model_engine.Engine({}, root)
            events = []
            with patch.object(engine, "unload_ollama", side_effect=lambda: events.append("unload")), \
                 patch.object(engine, "start_comfy", side_effect=lambda: events.append("start")), \
                 patch.object(engine, "stop_comfy", side_effect=lambda: events.append("stop")), \
                 patch.object(model_engine, "api", side_effect=RuntimeError("invalid workflow")):
                with self.assertRaises(RuntimeError):
                    engine.render("image", "a cat")
            self.assertEqual(events, ["unload", "start", "stop"])
            engine.executor.shutdown()

    def test_unload_failure_prevents_comfy_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workflows").mkdir()
            (root / "workflows/image.json").write_text(json.dumps(
                {"1": {"inputs": {"text": "__LOCAL_AI_PROMPT__"}}}))
            engine = model_engine.Engine({}, root)
            with patch.object(engine, "unload_ollama", side_effect=RuntimeError("still loaded")), \
                 patch.object(engine, "start_comfy") as start:
                with self.assertRaises(RuntimeError):
                    engine.render("image", "a cat")
                start.assert_not_called()
            engine.executor.shutdown()

    def test_two_requests_never_run_concurrently(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({}, Path(directory))
            started = threading.Event()
            finish = threading.Event()
            events = []
            def run(messages, route, prompt, body):
                events.append("start " + prompt)
                if prompt == "first":
                    started.set()
                    finish.wait(3)
                events.append("end " + prompt)
                return prompt
            with patch.object(engine, "run", side_effect=run):
                first = engine.submit(request("first"))
                self.assertTrue(started.wait(1))
                second = engine.submit(request("second"))
                self.assertFalse(second.running())
                finish.set()
                self.assertEqual(first.result(3), "first")
                self.assertEqual(second.result(3), "second")
            self.assertEqual(events, ["start first", "end first", "start second", "end second"])
            engine.executor.shutdown()

    def test_process_teardown_terminates_and_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = model_engine.Engine({}, Path(directory))
            process = unittest.mock.Mock(pid=123)
            process.poll.return_value = 0
            engine.process = process
            with patch.object(model_engine.os, "killpg") as kill, \
                 patch.object(model_engine, "port_open", return_value=False):
                engine.stop_comfy()
            kill.assert_called_once_with(123, model_engine.signal.SIGTERM)
            process.wait.assert_called_once_with(timeout=15)
            self.assertIsNone(engine.process)
            engine.executor.shutdown()

    def test_workflow_links_refer_to_existing_nodes_and_video_is_small(self):
        for kind in ("image", "video"):
            template = json.loads((model_engine.ROOT / "workflows" / f"{kind}.json").read_text())
            workflows.fill_workflow(template, "smoke test")
            for node in template.values():
                for value in node["inputs"].values():
                    if isinstance(value, list):
                        self.assertIn(value[0], template)
        self.assertEqual(template["70"]["inputs"]["length"], 17)
        self.assertEqual(template["70"]["inputs"]["batch_size"], 1)


if __name__ == "__main__":
    unittest.main()

