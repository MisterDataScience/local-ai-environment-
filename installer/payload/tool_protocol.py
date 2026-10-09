"""Translate tool messages, not execute tools. Open WebUI owns the agent loop."""
import copy
import json
import re
import uuid
from image_inputs import parts_to_message, MAX_IMAGES_PER_REQUEST


def function_call(value):
    if not isinstance(value, dict) or not isinstance(value.get("function"), dict):
        raise ValueError("Malformed function call")
    function = value["function"]
    name, arguments = function.get("name"), function.get("arguments")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", name):
        raise ValueError("Invalid function name")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            raise ValueError("Invalid function argument JSON") from None
    if not isinstance(arguments, dict) or len(json.dumps(arguments).encode()) > 65536:
        raise ValueError("Invalid or oversized function arguments")
    return {"name": name, "arguments": copy.deepcopy(arguments)}


def tools_for_ollama(body):
    tools = body.get("tools", [])
    if not isinstance(tools, list) or len(tools) > 128 or len(json.dumps(tools).encode()) > 262144:
        raise ValueError("Invalid or oversized tool definitions")
    names = set()
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ValueError("Only function tools are supported")
        function = tool.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("parameters", {}), dict):
            raise ValueError("Invalid function definition")
        name = function_call({"function": {"name": function.get("name"), "arguments": {}}})["name"]
        if name in names:
            raise ValueError("Duplicate function definition")
        names.add(name)
    choice = body.get("tool_choice", "auto")
    if choice not in ("auto", "none", None):
        raise ValueError("This native Ollama bridge supports tool_choice auto or none only")
    return copy.deepcopy(tools) if choice != "none" else []


def messages_for_ollama(messages):
    if not isinstance(messages, list) or not messages or len(messages) > 500:
        raise ValueError("messages must contain 1–500 entries")
    result, pending, seen = [], {}, set()
    image_count = 0
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each message must be an object")
        role = message.get("role")
        if role not in {"system", "developer", "user", "assistant", "tool"}:
            raise ValueError("Unsupported message role")
        content = message.get("content")
        if content is None and role == "assistant" and message.get("tool_calls"):
            content = ""
        content, images = parts_to_message(content, role)
        image_count += len(images)
        if image_count > MAX_IMAGES_PER_REQUEST:
            raise ValueError("Too many images in one request")
        if not isinstance(content, str):
            raise ValueError("Only text content is supported; image/audio inputs are not implemented")
        clean = {"role": "system" if role == "developer" else role, "content": content}
        if images:
            clean["images"] = images
        if role == "tool":
            identifier = message.get("tool_call_id")
            if not isinstance(identifier, str) or identifier not in pending:
                raise ValueError("Tool result has no matching pending call")
            clean["tool_name"] = pending.pop(identifier)
        elif pending:
            raise ValueError("Missing tool results before the next message")
        calls = message.get("tool_calls", [])
        if calls:
            if role != "assistant" or not isinstance(calls, list) or len(calls) > 32:
                raise ValueError("Invalid assistant tool calls")
            clean["tool_calls"] = []
            for call in calls:
                function = function_call(call)
                identifier = call.get("id")
                if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200 or identifier in seen:
                    raise ValueError("Invalid or duplicate tool call ID")
                seen.add(identifier)
                pending[identifier] = function["name"]
                clean["tool_calls"].append({"function": function})
        if role == "assistant" and isinstance(message.get("reasoning_content"), str):
            clean["thinking"] = message["reasoning_content"]
        result.append(clean)
    if pending:
        raise ValueError("Tool calls require corresponding results before inference")
    return result


def assistant_for_openai(message, tools):
    if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
        raise RuntimeError("Invalid assistant response from Ollama")
    content = message.get("content", "")
    if not isinstance(content, str):
        raise RuntimeError("Invalid assistant text")
    calls = message.get("tool_calls", [])
    if not isinstance(calls, list) or len(calls) > 32:
        raise RuntimeError("Invalid tool calls from Ollama")
    if not calls:
        return content
    names = {t["function"]["name"] for t in tools}
    output = {"role": "assistant", "content": content, "tool_calls": []}
    for call in calls:
        try:
            function = function_call(call)
        except ValueError as error:
            raise RuntimeError(str(error)) from None
        if function["name"] not in names:
            raise RuntimeError("Ollama requested a tool that was not supplied by Open WebUI")
        output["tool_calls"].append({"id": "call_" + uuid.uuid4().hex, "type": "function",
            "function": {"name": function["name"], "arguments": json.dumps(function["arguments"], ensure_ascii=False)}})
    if isinstance(message.get("thinking"), str):
        output["reasoning_content"] = message["thinking"]
    return output
