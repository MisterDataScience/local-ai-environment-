import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tool_registry as registry
import tool_executor as executor
import tool_loop as loop


def payload():
    return {"model": "qwen3:4b", "messages": [{"role": "user", "content": "Calculate"}],
            "options": {"num_ctx": 4096}, "keep_alive": 120, "stream": False, "think": False}


def reply(calls=None, content="", **extra):
    return {"message": {"role": "assistant", "content": content, "tool_calls": calls or [], **extra}}


def call(name="calculate", arguments=None):
    return {"function": {"name": name, "arguments": {"expression": "2+3"} if arguments is None else arguments}}


class RegistryTests(unittest.TestCase):
    def test_registry_has_only_two_tools_and_returns_a_copy(self):
        definitions = registry.definitions()
        self.assertEqual({t["function"]["name"] for t in definitions}, {"calculate", "get_current_time"})
        definitions.clear()
        self.assertEqual(len(registry.definitions()), 2)

    def test_arithmetic_precedence_and_allowed_operators(self):
        for expression, expected in (("(2+3)*4", 20), ("-2**2", -4), ("7//2 + 7%2", 4), ("1/4", .25)):
            self.assertEqual(registry.invoke("calculate", {"expression": expression})["value"], expected)

    def test_code_names_attributes_and_functions_are_not_executed(self):
        for expression in ("__import__('os').system('echo unsafe')", "open('secret')", "x+1", "[1,2]", "True", "(1).__class__"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                registry.invoke("calculate", {"expression": expression})

    def test_arithmetic_numeric_and_complexity_limits(self):
        for expression in ("2**1000000", "1e309", "1e101", "(-1)**0.5", "+".join(["1"] * 40)):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                registry.invoke("calculate", {"expression": expression})

    def test_strict_argument_validation(self):
        for name, arguments in (("shell", {}), ("calculate", {}), ("calculate", {"expression": 2}),
                                ("calculate", {"expression": "1", "path": "/"}), ("calculate", []),
                                ("get_current_time", {"timezone": "not/a/zone"}),
                                ("get_current_time", {"timezone": "UTC", "extra": 1})):
            with self.subTest(name=name, arguments=arguments), self.assertRaises(ValueError):
                registry.validate(name, arguments)

    def test_current_time_uses_london_by_default_and_accepts_utc(self):
        self.assertEqual(registry.invoke("get_current_time", {})["timezone"], "Europe/London")
        self.assertIn("+00:00", registry.invoke("get_current_time", {"timezone": "UTC"})["datetime"])


class ExecutorTests(unittest.TestCase):
    def test_real_isolated_worker_calculates_and_reads_time(self):
        self.assertEqual(executor.execute("calculate", {"expression": "(2+3)*4"}), {"ok": True, "result": {"value": 20}})
        self.assertTrue(executor.execute("get_current_time", {"timezone": "UTC"})["ok"])

    def test_invalid_call_never_launches_a_process(self):
        with patch.object(executor.subprocess, "Popen") as launched:
            result = executor.execute("shell", {})
            self.assertFalse(result["ok"])
            launched.assert_not_called()

    def test_timeout_kills_and_reaps_worker(self):
        worker = Mock(returncode=-9)
        worker.communicate.side_effect = [subprocess.TimeoutExpired("worker", 1), (b"", b"")]
        worker.poll.return_value = -9
        with patch.object(executor.subprocess, "Popen", return_value=worker) as launched:
            result = executor.execute("calculate", {"expression": "1"})
        worker.kill.assert_called_once()
        self.assertEqual(worker.communicate.call_count, 2)
        self.assertEqual(result["error"]["code"], "tool_timeout")
        self.assertEqual(launched.call_args.kwargs["env"], {})
        self.assertNotIn("shell", launched.call_args.kwargs)

    def test_real_process_is_terminated_on_tiny_deadline(self):
        original = executor.subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child = original([sys.executable, "-I", "-c", "import time; time.sleep(30)"], **kwargs)
            children.append(child)
            return child
        with patch.object(executor.subprocess, "Popen", side_effect=launch):
            result = executor.execute("calculate", {"expression": "1"}, timeout=.00001)
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(result["error"]["code"], "tool_timeout")

    def test_worker_start_failure_is_structured(self):
        with patch.object(executor.subprocess, "Popen", side_effect=OSError("start failed")):
            self.assertEqual(executor.execute("calculate", {"expression": "1"})["error"]["code"], "worker_failure")

    def test_calculation_failure_is_structured_not_success(self):
        result = executor.execute("calculate", {"expression": "1/0"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "tool_error")

    def test_bad_or_oversized_worker_response_is_rejected(self):
        for output in (b"not json", b"x" * 4097, b'{}'):
            worker = Mock(returncode=0)
            worker.communicate.return_value = (output, b"")
            worker.poll.return_value = 0
            with patch.object(executor.subprocess, "Popen", return_value=worker):
                self.assertFalse(executor.execute("calculate", {"expression": "1"})["ok"])


class LoopTests(unittest.TestCase):
    def test_plain_answer_does_not_execute_tools_or_mutate_input(self):
        request = payload()
        original = copy.deepcopy(request)
        api = Mock(return_value=reply(content="hello"))
        with patch.object(loop, "execute") as execute:
            self.assertEqual(loop.run_chat(api, "local", request), "hello")
            execute.assert_not_called()
        self.assertEqual(request, original)
        self.assertEqual(api.call_args.args[2]["model"], "qwen3:4b")
        self.assertEqual(api.call_args.args[2]["keep_alive"], 120)
        self.assertEqual(len(api.call_args.args[2]["tools"]), 2)

    def test_multiple_rounds_return_matching_results_and_preserve_thinking(self):
        api = Mock(side_effect=[reply([call()], thinking="private reasoning"),
                              reply([call(arguments={"expression": "5*2"})]), reply(content="10")])
        with patch.object(loop, "execute", side_effect=[{"ok": True, "result": {"value": 5}},
                                                       {"ok": True, "result": {"value": 10}}]) as execute:
            self.assertEqual(loop.run_chat(api, "local", payload()), "10")
        self.assertEqual(execute.call_count, 2)
        messages = api.call_args.args[2]["messages"]
        results = [m for m in messages if m["role"] == "tool"]
        self.assertEqual([json.loads(m["content"])["result"]["value"] for m in results], [5, 10])
        self.assertEqual(results[0]["tool_name"], "calculate")
        self.assertEqual(messages[2]["thinking"], "private reasoning")

    def test_multiple_tools_execute_sequentially(self):
        api = Mock(side_effect=[reply([call(), call("get_current_time", {})]), reply(content="done")])
        with patch.object(loop, "execute", return_value={"ok": True}) as execute:
            loop.run_chat(api, "local", payload())
        self.assertEqual([c.args[0] for c in execute.call_args_list], ["calculate", "get_current_time"])

    def test_json_string_arguments_supported(self):
        api = Mock(side_effect=[reply([call(arguments='{"expression":"2+3"}')]), reply(content="5")])
        with patch.object(loop, "execute", return_value={"ok": True}) as execute:
            loop.run_chat(api, "local", payload())
        self.assertEqual(execute.call_args.args[1], {"expression": "2+3"})

    def test_unknown_tool_result_is_an_error_not_arbitrary_execution(self):
        api = Mock(side_effect=[reply([call("shell", {})]), reply(content="Tool unavailable")])
        self.assertEqual(loop.run_chat(api, "local", payload()), "Tool unavailable")
        result = json.loads(api.call_args.args[2]["messages"][-1]["content"])
        self.assertFalse(result["ok"])

    def test_round_limit_stops_runaway_model(self):
        api = Mock(return_value=reply([call()]))
        with patch.object(loop, "execute", return_value={"ok": True}) as execute:
            with self.assertRaisesRegex(RuntimeError, "limit"):
                loop.run_chat(api, "local", payload())
        self.assertEqual(execute.call_count, 6)
        self.assertEqual(api.call_count, 7)

    def test_call_limit_rejects_whole_batch_before_execution(self):
        api = Mock(return_value=reply([call()] * 13))
        with patch.object(loop, "execute") as execute:
            with self.assertRaises(RuntimeError):
                loop.run_chat(api, "local", payload())
            execute.assert_not_called()

    def test_malformed_batch_executes_nothing(self):
        for bad in ({}, {"function": {"name": "calculate", "arguments": "bad json"}}, {"function": []}):
            api = Mock(return_value=reply([call(), bad]))
            with patch.object(loop, "execute") as execute:
                with self.assertRaises(RuntimeError):
                    loop.run_chat(api, "local", payload())
                execute.assert_not_called()

    def test_evidence_and_context_limits_stop_loop(self):
        api = Mock(return_value=reply([call()]))
        with patch.object(loop, "MAX_EVIDENCE_BYTES", 1), patch.object(loop, "execute", return_value={"ok": True}):
            with self.assertRaisesRegex(RuntimeError, "evidence"):
                loop.run_chat(api, "local", payload())
        request = payload()
        request["messages"][0]["content"] = "x" * 20000
        api = Mock()
        with self.assertRaisesRegex(RuntimeError, "context"):
            loop.run_chat(api, "local", request)
        api.assert_not_called()

    def test_expired_deadline_prevents_tools(self):
        api = Mock(return_value=reply([call()]))
        with patch.object(loop.time, "monotonic", side_effect=[0, 0, 901]), patch.object(loop, "execute") as execute:
            with self.assertRaisesRegex(RuntimeError, "time limit"):
                loop.run_chat(api, "local", payload())
            execute.assert_not_called()

    def test_disabled_loop_sends_no_tools(self):
        api = Mock(return_value=reply(content="ordinary"))
        self.assertEqual(loop.run_chat(api, "local", payload(), enabled=False), "ordinary")
        self.assertNotIn("tools", api.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
