"""Read-only, on-demand index of configured LOCAL AI capabilities.

Never describes a registered tool as granted, selected, or operational.
No health probes, background discovery, model inference, or account data.
"""

KINDS = ("all", "web", "files", "workspace", "browser", "office", "coding",
         "media", "desktop", "delegation", "accounts")


def specification():
    return {
        "openapi": "3.0.3",
        "info": {"title": "LOCAL AI capability discovery", "version": "1"},
        "servers": [{"url": "http://127.0.0.1:8001"}],
        "paths": {"/capabilities/discover_local_capabilities": {"post": {
            "operationId": "discover_local_capabilities",
            "description": (
                "Read-only index of LOCAL AI features that may require separate activation. "
                "Call only when a task needs a capability not already exposed; never for "
                "ordinary questions. Configured does not mean accessible, selected, or ready."
            ),
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": {"type": "object", "properties": {
                    "category": {"type": "string", "enum": list(KINDS),
                                 "description": "Relevant category, or all"}},
                    "additionalProperties": False}}}},
            "responses": {"200": {"description": "Bounded, non-sensitive capability index"}}
        }}},
        "security": [{"bearerAuth": []}],
        "components": {"securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer"}}},
    }


def discover(config, arguments):
    if not isinstance(arguments, dict) or set(arguments) - {"category"}:
        raise ValueError("Only the category field is accepted")
    category = arguments.get("category", "all")
    if not isinstance(category, str) or category not in KINDS:
        raise ValueError("Unknown capability category")
    if not isinstance(config, dict):
        raise ValueError("Invalid local configuration")
    web = bool(config.get("web", {}).get("enabled"))
    guarded = bool(config.get("desktop", {}).get("enabled") or
                   config.get("external_delegation", {}).get("enabled"))
    entries = {
        "web": (web and not guarded, "Open WebUI: select Local AI VPN retrieval under Integrations"),
        "files": (not guarded, "Open WebUI: select Local AI file workflows under Integrations"),
        "workspace": (bool(config.get("vault", {}).get("enabled")) and not guarded,
                      "Open WebUI: select Encrypted AI Workspace; unlock vault separately"),
        "browser": (web and bool(config.get("browser", {}).get("enabled")) and not guarded,
                    "Open WebUI: select Playwright browser under Integrations"),
        "office": (bool(config.get("office", {}).get("enabled")),
                   "OpenCode: Plan can inspect; Build writes with approval"),
        "coding": (bool(config.get("model_team", {}).get("enabled")),
                   "OpenCode: coordinator and approved coding specialist"),
        "media": (not guarded, "OpenCode: explicit image/video/speech requests; mode restrictions apply"),
        "desktop": (bool(config.get("desktop", {}).get("enabled")),
                    "Guarded OpenCode automation session only; explicit approval required"),
        "delegation": (bool(config.get("external_delegation", {}).get("enabled")),
                       "Guarded OpenCode automation session only; privacy and provider restrictions apply"),
        "accounts": (bool(config.get("account_tools", {}).get("github")) and not guarded,
                     "Open WebUI: separately select configured account integration; approval required"),
    }
    chosen = KINDS[1:] if category == "all" else (category,)
    return {
        "status": "configuration_only",
        "notice": ("These are configuration indicators, not live health checks, "
                   "permissions or current-chat tool selection. Use only tools "
                   "actually exposed to this session and respect approvals."),
        "capabilities": [
            {"category": kind, "configured": bool(entries[kind][0]),
             "access": entries[kind][1]}
            for kind in chosen
        ],
    }
