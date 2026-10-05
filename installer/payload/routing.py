"""Validate chat messages and recognise explicit commands. No I/O."""

MODEL_ID = "local-ai"


def messages_and_route(body, model_ids=None):
    if not isinstance(body, dict):
        raise ValueError("The request body must be a JSON object.")
    if body.get("model") not in (model_ids if model_ids is not None else {MODEL_ID}):
        raise ValueError("Choose one of the configured local-ai text presets in Open WebUI.")
    if body.get("tools"):
        raise ValueError("Client-supplied tools are not permitted. The gateway owns its tool registry.")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list.")
    cleaned = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each message must be an object.")
        role, content = message.get("role"), message.get("content")
        if role not in {"system", "user", "assistant", "developer"}:
            raise ValueError("Only ordinary text chat messages are supported.")
        if not isinstance(content, str):
            raise ValueError("Use text prompts. Image/audio attachments are not implemented.")
        cleaned.append({"role": "system" if role == "developer" else role, "content": content})
    latest = next((m["content"] for m in reversed(cleaned) if m["role"] == "user"), "")
    stripped = latest.strip()
    # Whitespace after a command may also be a newline or a tab.
    parts = stripped.split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    if command in {"/image", "/video", "/search", "/read"}:
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("Put a description/query/URL after the command.")
        return cleaned, command[1:], parts[1].strip()
    return cleaned, "text", latest
