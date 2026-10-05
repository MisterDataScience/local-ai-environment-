"""Run allowlisted tools in a short-lived process with a real kill deadline."""
import json
from pathlib import Path
import subprocess
import sys
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from tool_registry import invoke, validate

MAX_RESULT_BYTES = 4096
TOOL_TIMEOUT_SECONDS = 5


def error(code, message):
    return {"ok": False, "error": {"code": code, "message": message[:300]}}


def execute(name, arguments, timeout=TOOL_TIMEOUT_SECONDS):
    try:
        arguments = validate(name, arguments)
    except ValueError as failure:
        return error("invalid_call", str(failure))
    # Credentials/configuration are not passed to the worker, nor is a shell used.
    command = [sys.executable, "-I", str(Path(__file__).resolve()), "--worker"]
    try:
        worker = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env={}, text=False)
    except OSError:
        return error("worker_failure", "Tool worker could not start")
    try:
        try:
            output, _ = worker.communicate(json.dumps({"name": name, "arguments": arguments}).encode(),
                                           timeout=max(0.01, min(timeout, TOOL_TIMEOUT_SECONDS)))
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.communicate()
            return error("tool_timeout", "Tool execution exceeded its deadline and was terminated")
        if worker.returncode or len(output) > MAX_RESULT_BYTES:
            return error("worker_failure", "Tool worker failed or returned too much data")
        result = json.loads(output)
        if not isinstance(result, dict) or type(result.get("ok")) is not bool:
            raise ValueError("Invalid worker result")
        return result
    except (ValueError, OSError):
        return error("worker_failure", "Invalid tool worker response")
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate()


def main():
    # Isolated Python ignores the script directory: add only this trusted directory.
    data = sys.stdin.buffer.read(8193)
    try:
        if len(data) > 8192:
            raise ValueError("Worker request too large")
        request = json.loads(data)
        result = {"ok": True, "result": invoke(request["name"], request["arguments"])}
    except Exception as failure:
        result = error("tool_error", str(failure))
    encoded = json.dumps(result, allow_nan=False).encode()
    if len(encoded) > MAX_RESULT_BYTES:
        encoded = json.dumps(error("result_limit", "Tool result exceeds 4 KiB")).encode()
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    main()
