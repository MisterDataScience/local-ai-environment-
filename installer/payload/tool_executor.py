"""Run allowlisted tools in a short-lived process with a real kill deadline."""
import json
from pathlib import Path
import subprocess
import sys
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from tool_registry import invoke, validate, WEB_NAMES

MAX_RESULT_BYTES = 4096
TOOL_TIMEOUT_SECONDS = 5


def error(code, message):
    return {"ok": False, "error": {"code": code, "message": message[:300]}}


def execute(name, arguments, timeout=None, web=None):
    try:
        arguments = validate(name, arguments)
    except ValueError as failure:
        return error("invalid_call", str(failure))
    is_web = name in WEB_NAMES
    if is_web and (not isinstance(web, dict) or not web.get("enabled") or web.get("url") != "http://127.0.0.1:8090"):
        return error("web_disabled", "VPN web access is not configured; no fallback is allowed")
    limit = 140 if is_web else TOOL_TIMEOUT_SECONDS
    timeout = limit if timeout is None else max(0.01, min(timeout, limit))
    payload = {"name": name, "arguments": arguments}
    if is_web:
        # Only this restricted configuration enters worker stdin, never model messages.
        payload["web"] = {"enabled": True, "url": web["url"], "api_key": web.get("api_key", "")}
    # Credentials/configuration are not passed to the worker, nor is a shell used.
    command = [sys.executable, "-I", str(Path(__file__).resolve()), "--worker"]
    try:
        worker = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env={}, text=False)
    except OSError:
        return error("worker_failure", "Tool worker could not start")
    try:
        try:
            output, _ = worker.communicate(json.dumps(payload).encode(), timeout=timeout)
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
        name, arguments = request["name"], validate(request["name"], request["arguments"])
        if name in WEB_NAMES:
            from web_client import fetch_sources
            kind = "search" if name == "search_web" else "read"
            sources = fetch_sources({"web": request.get("web", {})}, kind, arguments, text_budget=1500, timeout=135)[:3]
            for source in sources:
                source["title"] = source["title"][:120]
                source["read_error"] = str(source["read_error"])[:120] if source["read_error"] else None
            result = {"ok": True, "result": {"sources": sources}}
            # Preserve whole URLs/labels; reduce evidence rather than cutting JSON.
            while len(json.dumps(result).encode()) > MAX_RESULT_BYTES - 256 and any(s["text"] for s in sources):
                for source in sources:
                    source["text"] = source["text"][:len(source["text"]) // 2]
                    source["truncated"] = True
        else:
            result = {"ok": True, "result": invoke(name, arguments)}
    except Exception as failure:
        result = error("tool_error", str(failure))
    encoded = json.dumps(result, allow_nan=False).encode()
    if len(encoded) > MAX_RESULT_BYTES:
        encoded = json.dumps(error("result_limit", "Tool result exceeds 4 KiB")).encode()
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    main()
