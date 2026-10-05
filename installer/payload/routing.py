"""Validate chat messages and recognise explicit commands. No I/O."""

MODEL_ID = "local-ai"
from tool_protocol import messages_for_ollama, tools_for_ollama


def messages_and_route(body, model_ids=None):
    if not isinstance(body, dict):
        raise ValueError("The request body must be a JSON object.")
    if body.get("model") not in (model_ids if model_ids is not None else {MODEL_ID}):
        raise ValueError("Choose one of the configured local-ai text presets in Open WebUI.")
    tools_for_ollama(body)  # Validate schemas before admitting a job; never execute them.
    cleaned = messages_for_ollama(body.get("messages"))
    latest = next((m["content"] for m in reversed(cleaned) if m["role"] == "user"), "")
    stripped = latest.strip()
    # Whitespace after a command may also be a newline or a tab.
    parts = stripped.split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    if cleaned[-1]["role"] == "user" and command in {"/image", "/video", "/search", "/read"}:
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("Put a description/query/URL after the command.")
        return cleaned, command[1:], parts[1].strip()
    return cleaned, "text", latest
