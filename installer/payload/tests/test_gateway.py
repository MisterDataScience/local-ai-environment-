import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway


def request(text):
    return {"model": "local-ai", "messages": [{"role": "user", "content": text}]}


class GatewayTests(unittest.TestCase):
    def test_commands_route_only_on_latest_user_message(self):
        body = request("Explain what /video does")
        self.assertEqual(gateway.messages_and_route(body)[1], "text")
        body["messages"].insert(0, {"role": "user", "content": "/image old request"})
        self.assertEqual(gateway.messages_and_route(body)[1], "text")
        self.assertEqual(gateway.messages_and_route(request("/VIDEO\nA cat walks"))[1:],
                         ("video", "A cat walks"))

    def test_empty_command_and_unsupported_attachments_fail(self):
        with self.assertRaises(ValueError):
            gateway.messages_and_route([])
        with self.assertRaises(ValueError):
            gateway.messages_and_route(request("/image"))
        body = request("text")
        body["messages"][0]["content"] = [{"type": "image_url"}]
        with self.assertRaises(ValueError):
            gateway.messages_and_route(body)

    def test_template_does_not_mutate_and_seeds_agree(self):
        template = {"1": {"inputs": {"text": "__LOCAL_AI_PROMPT__", "seed": 0}},
                    "2": {"inputs": {"noise_seed": 0}}}
        output = gateway.fill_workflow(template, "a landscape")
        self.assertEqual(template["1"]["inputs"]["text"], "__LOCAL_AI_PROMPT__")
        self.assertEqual(output["1"]["inputs"]["text"], "a landscape")
        self.assertEqual(output["1"]["inputs"]["seed"], output["2"]["inputs"]["noise_seed"])

    def test_unload_all_models_then_poll_for_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = gateway.Engine({}, Path(directory))
            events = []
            replies = iter([{"models": [{"name": "one"}, {"name": "two"}]}, {"models": []}])
            def fake_api(base, path, payload=None, timeout=30):
                events.append((path, payload))
                return next(replies) if path == "/api/ps" else {}
            with patch.object(gateway, "api", side_effect=fake_api):
                engine.unload_ollama()
            self.assertEqual([event[0] for event in events],
                             ["/api/ps", "/api/generate", "/api/generate", "/api/ps"])
            self.assertTrue(all(event[1]["keep_alive"] == 0 for event in events[1:3]))
            engine.executor.shutdown()

    def test_http_authentication_and_stream_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = gateway.Engine({"api_key": "test-key"}, Path(directory))
            server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
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
            engine = gateway.Engine({}, root)
            events = []
            with patch.object(engine, "unload_ollama", side_effect=lambda: events.append("unload")), \
                 patch.object(engine, "start_comfy", side_effect=lambda: events.append("start")), \
                 patch.object(engine, "stop_comfy", side_effect=lambda: events.append("stop")), \
                 patch.object(gateway, "api", side_effect=RuntimeError("invalid workflow")):
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
            engine = gateway.Engine({}, root)
            with patch.object(engine, "unload_ollama", side_effect=RuntimeError("still loaded")), \
                 patch.object(engine, "start_comfy") as start:
                with self.assertRaises(RuntimeError):
                    engine.render("image", "a cat")
                start.assert_not_called()
            engine.executor.shutdown()

    def test_two_requests_never_run_concurrently(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = gateway.Engine({}, Path(directory))
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
            engine = gateway.Engine({}, Path(directory))
            process = unittest.mock.Mock(pid=123)
            process.poll.return_value = 0
            engine.process = process
            with patch.object(gateway.os, "killpg") as kill, \
                 patch.object(gateway, "port_open", return_value=False):
                engine.stop_comfy()
            kill.assert_called_once_with(123, gateway.signal.SIGTERM)
            process.wait.assert_called_once_with(timeout=15)
            self.assertIsNone(engine.process)
            engine.executor.shutdown()

    def test_workflow_links_refer_to_existing_nodes_and_video_is_small(self):
        for kind in ("image", "video"):
            template = json.loads((gateway.ROOT / "workflows" / f"{kind}.json").read_text())
            gateway.fill_workflow(template, "smoke test")
            for node in template.values():
                for value in node["inputs"].values():
                    if isinstance(value, list):
                        self.assertIn(value[0], template)
        self.assertEqual(template["70"]["inputs"]["length"], 17)
        self.assertEqual(template["70"]["inputs"]["batch_size"], 1)


if __name__ == "__main__":
    unittest.main()
