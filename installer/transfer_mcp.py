"""Native-approval MCP file handoff into a single active Work Agent project.

No agent-selected project id, no generic filesystem access, no hidden vault
unlocking. Each import/export is a create-only copy within fixed roots.
"""
import argparse
import json
from pathlib import Path
import sys

from file_transfer import transfer
from vault_transfer import transfer_vault

TOOLS = [{"name": "transfer_file",
          "description": ("Copy a file into/out of the active project from the Playwright "
                          "browser download directory or manually unlocked encrypted vault. "
                          "Requires native user approval. Vault import creates plaintext "
                          "data in the project. Refuses overwrites and traversal."),
          "inputSchema": {
              "type": "object",
              "properties": {
                  "direction": {"type": "string", "enum": [
                      "browser-import", "browser-export", "vault-import", "vault-export"]},
                  "path": {"type": "string", "minLength": 1,
                           "description": "Relative path inside source root. Vault import starts with Inbox/, Projects/, Outputs/ or Archive/."}},
              "required": ["direction", "path"], "additionalProperties": False}}]


def dispatch(message, root, project):
    method, rid = message.get("method"), message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "local-ai-project-transfers", "version": "1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params", {})
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        if (not isinstance(params, dict) or params.get("name") != "transfer_file"
                or not isinstance(arguments, dict) or set(arguments) != {"path", "direction"}):
            return _error(rid, -32602, "Invalid file transfer request")
        direction, path = arguments["direction"], arguments["path"]
        if not isinstance(direction, str) or not isinstance(path, str) or not 0 < len(path) <= 2048:
            return _error(rid, -32602, "Invalid transfer parameters")
        try:
            if direction in {"browser-import", "browser-export"}:
                output = transfer(root, project.name, path,
                                  direction=direction.removeprefix("browser-"))
            elif direction in {"vault-import", "vault-export"}:
                config = json.loads((root / "control/config.json").read_text())
                output = transfer_vault(config, root, project.name, path, direction)
            else:
                return _error(rid, -32602, "Unknown transfer direction")
            result = {"content": [{"type": "text", "text": json.dumps({
                "saved": str(output), "notice": "Transfer created a separate file copy. No file overwritten."})}]}
        except (OSError, RuntimeError, ValueError) as error:
            result = {"content": [{"type": "text", "text": str(error)[:600]}], "isError": True}
    else:
        return _error(rid, -32601, "Method not found")
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    project = args.project.resolve(strict=True)
    if (project.parent != (root / "work-agent/projects").resolve(strict=True)
            or len(project.name) != 32 or any(c not in "0123456789abcdef" for c in project.name)):
        raise SystemExit("Must run for an active Work Agent project")
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError()
            response = dispatch(request, root, project)
        except (ValueError, TypeError, KeyError):
            response = _error(None, -32700, "Invalid JSON-RPC message")
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
