"""Opt-in Playwright MCP browser sharing the existing Gluetun VPN network namespace.

The browser is NEVER spawned on the Mac. All external browser traffic originates
in a container with network_mode=service:vpn. Do not add a host-side fallback.
"""
import argparse
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

from web_access import (IMAGES, BROWSER_IMAGE, compose, docker_command,
                        pull_verified_image, save, specification)

IMAGE = BROWSER_IMAGE
URL = "http://127.0.0.1:8931/mcp"


def image_digest(binary):
    """Install the managed release's browser digest, including cache repair."""
    return pull_verified_image(binary, IMAGE)


def mcp_probe(timeout=5):
    """Check a real MCP initialise response, not merely an open TCP port."""
    request = Request(URL, method="POST",
                      data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                       "params": {"protocolVersion": "2025-06-18",
                                                  "capabilities": {},
                                                  "clientInfo": {"name": "local-ai-browser-check",
                                                                 "version": "1"}}}).encode(),
                      headers={"Content-Type": "application/json",
                               "Accept": "application/json, text/event-stream"})
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        data = response.read(65536).decode("utf-8")
    for line in data.splitlines():
        candidate = line.removeprefix("data: ").strip()
        if not candidate.startswith("{"):
            continue
        message = json.loads(candidate)
        if message.get("id") == 1 and isinstance(message.get("result", {}).get("serverInfo"), dict):
            return message["result"]["serverInfo"]
    raise RuntimeError("Playwright endpoint did not return an MCP initialise response.")


def wait_ready(timeout=45):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return mcp_probe(timeout=3)
        except (OSError, ValueError, RuntimeError, HTTPError, URLError) as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError(f"Playwright MCP did not become ready: {last_error}")


def configure(root, *, disable=False):
    """Idempotent setup, guarded against changes while Local AI is running."""
    import fcntl
    root = Path(root).expanduser().resolve()
    lock = (root / ".runtime.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("Stop Local AI before configuring its browser.")
    try:
        config_path = root / "control/config.json"
        config = json.loads(config_path.read_text())
        if not config.get("web", {}).get("enabled"):
            raise RuntimeError("Enable the Gluetun/Proton VPN web stack first. No direct-network browser is allowed.")
        web = root / "web"
        lock_path = web / "images.json"
        images = json.loads(lock_path.read_text())
        if not disable and any(images.get(name) != image for name, image in IMAGES.items()):
            raise RuntimeError("VPN images do not match this release. Rerun the Captain installer first.")
        # Guard against other processes already holding the browser endpoint.
        if not disable and not config.get("browser", {}).get("enabled"):
            from common import port_open
            if port_open(8931):
                raise RuntimeError("Port 8931 is occupied; existing process was not stopped.")
        old_compose = (web / "compose.json").read_text()
        old_images = lock_path.read_text()
        old_config = config_path.read_text()
        if not disable:
            images["browser"] = image_digest(docker_command())
        if not disable:
            for name in ("browser-profile", "browser-outputs"):
                path = web / name
                if path.is_symlink():
                    raise RuntimeError("Browser data directories cannot be symlinks.")
                path.mkdir(mode=0o700, exist_ok=True)
                path.chmod(0o700)
        new_enabled = not disable
        config["browser"] = {"enabled": new_enabled, "url": URL}
        try:
            save(lock_path, images)
            save(web / "compose.json", specification(images, browser_enabled=new_enabled))
            save(config_path, config)
            # Remove any former browser container after disabling it.
            compose(root, "up", "--detach", "--force-recreate", "--remove-orphans",
                    "--pull", "never", timeout=180)
            if new_enabled:
                result = wait_ready()
                print("Playwright MCP ready:", result.get("name", "unknown"))
                print("Restart Local AI and enable Playwright browser in chat Integrations.")
            else:
                print("Playwright MCP disabled; profile and downloaded files retained locally.")
        except Exception:
            # Revert the installed configuration rather than claim half a setup is ready.
            (web / "compose.json").write_text(old_compose)
            (web / "images.json").write_text(old_images)
            (config_path).write_text(old_config)
            for file in (web / "compose.json", lock_path, config_path):
                file.chmod(0o600)
            try:
                compose(root, "up", "--detach", "--force-recreate", "--remove-orphans",
                        "--pull", "never", timeout=180)
            except Exception:
                pass
            raise
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        config = json.loads((args.root.expanduser() / "control/config.json").read_text())
        if not (config.get("web", {}).get("enabled") and config.get("browser", {}).get("enabled")):
            raise RuntimeError("Playwright browser is not enabled.")
        print(json.dumps(mcp_probe(), indent=2))
    else:
        configure(args.root, disable=args.disable)


if __name__ == "__main__":
    main()
