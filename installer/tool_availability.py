"""Explicit, read-only inspection of LOCAL AI tool registration.

Runs only when requested. Does not invoke a model, activate a tool,
start a service, or change tool configuration or permissions.
"""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

from common import webui_environment
from context_settings import NoRedirect

OPENER = build_opener(ProxyHandler({}), NoRedirect())


def request(path, *, token=None, payload=None, port=8081):
    """Loopback request; never follow redirects or inherit HTTP proxies."""
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    with OPENER.open(Request(f"http://127.0.0.1:{port}" + path, data=data,
                            headers=headers), timeout=4) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Local configuration response too large")
        return json.loads(raw)


def audit(config, root):
    """Distinguish declared, registered and *selected* tools."""
    env = webui_environment(root, config)
    declared = [
        item.get("info", {}).get("id") for item in
        json.loads(env.get("TOOL_SERVER_CONNECTIONS", "[]"))
    ]
    if len(declared) != len(set(declared)) or not all(declared):
        raise RuntimeError("Invalid or duplicate configured tool server IDs")
    report = {
        "scope": "read-only registration; no inference or invocation",
        "configured_servers": declared,
        "gateway": "unverified",
        "webui": "unverified",
        "registered_servers": [],
        "missing_servers": [],
        "per_chat_selection": "not_verified",
        "opencode": "checked separately by the existing Work Agent startup checks",
    }
    try:
        spec = request("/capabilities/openapi.json", token=config["api_key"], port=8001)
        operations = [
            entry.get("post", {}).get("operationId")
            for entry in spec.get("paths", {}).values()
        ]
        report["gateway"] = ("discovery_spec_reachable"
                             if "discover_local_capabilities" in operations
                             else "unexpected_discovery_spec")
    except (HTTPError, URLError, OSError, ValueError, KeyError):
        report["gateway"] = "not_reachable_or_not_updated"
    try:
        login = request("/api/v1/auths/signin",
                        payload={"email": "admin@localhost", "password": ""})
        token = login["token"]
        servers = request("/api/v1/configs/tool_servers", token=token)
        listed = servers.get("TOOL_SERVER_CONNECTIONS", [])
        if not isinstance(listed, list):
            raise ValueError("Invalid registered connections")
        live_ids = {
            item.get("info", {}).get("id")
            for item in listed if isinstance(item, dict)
        }
        report["registered_servers"] = sorted(set(declared) & live_ids)
        report["missing_servers"] = sorted(set(declared) - live_ids)
        report["webui"] = ("registration_matches" if not report["missing_servers"]
                           else "registration_mismatch")
    except (HTTPError, URLError, OSError, ValueError, KeyError, TypeError):
        report["webui"] = "not_reachable_or_registration_unverified"
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.expanduser().resolve(strict=True)
    config = json.loads((root / "control/config.json").read_text())
    report = audit(config, root)
    print(json.dumps(report, indent=2))
    if report["gateway"] != "discovery_spec_reachable" or report["webui"] != "registration_matches":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
