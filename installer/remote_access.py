"""Optional private Tailscale access. Never enables Funnel or exit-node routing."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.request import urlopen
from urllib.error import HTTPError
import uuid

TAILSCALE_VERSION = "1.102.4"
TAILSCALE_PACKAGE = f"https://pkgs.tailscale.com/stable/Tailscale-{TAILSCALE_VERSION}-macos.pkg"
TAILSCALE_TEAM = "W5364U7YZB"
APP = Path("/Applications/Tailscale.app")
CLI = APP / "Contents/MacOS/Tailscale"
TARGETS = {443: "http://127.0.0.1:8081", 8443: "http://127.0.0.1:8002"}


def execute(command, capture=False, timeout=60):
    env = os.environ.copy()
    env["TAILSCALE_BE_CLI"] = "1"
    result = subprocess.run([str(arg) for arg in command], check=True, env=env,
                            capture_output=capture, text=True, timeout=timeout)
    return result.stdout if capture else ""


def cli_json(*args):
    return json.loads(execute([CLI, *args], capture=True))


def connected_hostname(status):
    if status.get("BackendState") != "Running":
        raise RuntimeError("Tailscale is not connected. Sign in and connect in its Mac app.")
    hostname = status.get("Self", {}).get("DNSName", "").rstrip(".")
    if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.ts\.net", hostname):
        raise RuntimeError("A valid Tailscale MagicDNS hostname is required for private HTTPS.")
    return hostname


def assert_private_ports(serve, hostname):
    for endpoint, enabled in serve.get("AllowFunnel", {}).items():
        if enabled and any(endpoint.endswith(f":{port}") for port in TARGETS):
            raise RuntimeError("Public Funnel is enabled on a Local AI port. Remote setup refuses public access.")


def check_conflicts(serve, hostname):
    assert_private_ports(serve, hostname)
    for port, target in TARGETS.items():
        endpoint = f"{hostname}:{port}"
        handlers = serve.get("Web", {}).get(endpoint, {}).get("Handlers", {})
        tcp = serve.get("TCP", {}).get(str(port))
        if handlers and handlers != {"/": {"Proxy": target}}:
            raise RuntimeError(f"Tailscale port {port} already serves another app. Nothing was replaced.")
        if tcp and (tcp != {"HTTPS": True} or not handlers):
            raise RuntimeError(f"Tailscale port {port} is already in use. Nothing was replaced.")
        # A Web mapping on the same port under an older hostname is also a conflict.
        for address in serve.get("Web", {}):
            if address.endswith(f":{port}") and address != endpoint:
                raise RuntimeError(f"Tailscale port {port} belongs to another hostname.")


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def install_client(root):
    if not CLI.is_file():
        if APP.exists():
            raise RuntimeError("An existing Tailscale app has an unexpected layout. It was not overwritten.")
        package = root / "cache" / f"Tailscale-{TAILSCALE_VERSION}-macos.pkg"
        package.parent.mkdir(parents=True, exist_ok=True)
        if not package.exists():
            partial = package.with_suffix(".pkg.part")
            execute(["/usr/bin/curl", "-fL", "--retry", "3", "--connect-timeout", "30",
                     "-C", "-", "-o", partial, TAILSCALE_PACKAGE], timeout=1800)
            partial.replace(package)
        signature = execute(["/usr/sbin/pkgutil", "--check-signature", package], capture=True)
        if f"Tailscale Inc. ({TAILSCALE_TEAM})" not in signature:
            raise RuntimeError("The downloaded package is not signed by the expected Tailscale publisher.")
        execute(["/usr/sbin/spctl", "--assess", "--type", "install", package])
        print("macOS will request administrator approval to install the signed Tailscale package.", flush=True)
        script = ('on run argv\n'
                  'do shell script "/usr/sbin/installer -pkg " & quoted form of (item 1 of argv) & '
                  '" -target /" with administrator privileges\nend run')
        execute(["/usr/bin/osascript", "-e", script, str(package)], timeout=1800)
    if not CLI.is_file():
        raise RuntimeError("Tailscale installation did not create its expected CLI.")
    execute(["/usr/bin/codesign", "--verify", "--deep", "--strict", APP])
    identity = subprocess.run(["/usr/bin/codesign", "-d", "--verbose=4", str(APP)],
                              check=True, capture_output=True, text=True, timeout=60)
    if f"TeamIdentifier={TAILSCALE_TEAM}" not in identity.stderr:
        raise RuntimeError("The installed app is not signed by the expected Tailscale team.")
    execute(["/usr/bin/open", "-a", str(APP)])


def wait_for_connection(timeout=900):
    print("In Tailscale, approve the macOS network/system extension and sign in to your personal account.", flush=True)
    print("Setup waits up to 15 minutes. No Tailscale password or auth key is stored by Local AI.", flush=True)
    deadline = time.monotonic() + timeout
    next_notice = 0
    while time.monotonic() < deadline:
        try:
            return connected_hostname(cli_json("status", "--json"))
        except (RuntimeError, subprocess.SubprocessError, ValueError):
            if time.monotonic() >= next_notice:
                print("Waiting for Tailscale sign-in, extension approval and a connected MagicDNS address...", flush=True)
                next_notice = time.monotonic() + 30
            time.sleep(2)
    raise RuntimeError("Tailscale is not ready. Complete its setup, then rerun Enable Remote Access.command.")


def configure(root):
    root = Path(root).expanduser().resolve()
    config_path = root / "control/config.json"
    if not config_path.exists():
        raise RuntimeError("Install Local AI first, then enable remote access.")
    install_client(root)
    print("Remote access uses Tailscale permissions, without an additional WebUI password.", flush=True)
    print("Use your personal tailnet: permitted devices can access the same chats and generated media.", flush=True)
    hostname = wait_for_connection()
    before = cli_json("serve", "status", "--json")
    check_conflicts(before, hostname)
    created = []
    try:
        for port, target in TARGETS.items():
            existed = bool(before.get("Web", {}).get(f"{hostname}:{port}", {}).get("Handlers"))
            if not existed:
                created.append(port)
            print(f"Configuring private HTTPS port {port}. Approve HTTPS in Tailscale if prompted.", flush=True)
            execute([CLI, "serve", "--bg", "--yes", f"--https={port}", target], timeout=900)
        after = cli_json("serve", "status", "--json")
        check_conflicts(after, hostname)
        for port, target in TARGETS.items():
            if after.get("Web", {}).get(f"{hostname}:{port}", {}).get("Handlers") != {"/": {"Proxy": target}}:
                raise RuntimeError("Tailscale did not confirm the requested private proxy configuration.")
        config = json.loads(config_path.read_text())
        if "remote_access" not in config:
            backup = config_path.with_name("config.before-remote-access.json")
            if not backup.exists():
                atomic_json(backup, config)
        config["remote_access"] = {"enabled": True, "hostname": hostname,
                                   "ui_url": f"https://{hostname}",
                                   "media_url": f"https://{hostname}:8443"}
        atomic_json(config_path, config)
    except BaseException:
        # Only undo routes created by this attempt; do not reset unrelated Serve services.
        for port in reversed(created):
            try:
                execute([CLI, "serve", "--bg", "--yes", f"--https={port}", "off"])
            except subprocess.SubprocessError:
                pass
        raise
    (root / "Remote AI Address.txt").write_text(
        f"Chat: https://{hostname}\nMedia: https://{hostname}:8443/media/FILE\n"
        "Install Tailscale on your other devices, sign in to the same account and bookmark Chat.\n"
        "The Mac must be awake and Local AI must be running.\n")
    print(f"Private chat address: https://{hostname}", flush=True)
    print("Restart Local AI if it was already running. Then test chat and generated media from another device.", flush=True)
    return config["remote_access"]


def disable(root):
    path = Path(root).expanduser().resolve() / "control/config.json"
    config = json.loads(path.read_text())
    remote = config.get("remote_access", {})
    if not remote.get("enabled"):
        return
    hostname = remote["hostname"]
    serve = cli_json("serve", "status", "--json")
    check_conflicts(serve, hostname)
    for port in TARGETS:
        if serve.get("Web", {}).get(f"{hostname}:{port}", {}).get("Handlers"):
            execute([CLI, "serve", "--bg", "--yes", f"--https={port}", "off"])
    config["remote_access"]["enabled"] = False
    atomic_json(path, config)
    print("Local AI remote routes disabled. Tailscale and unrelated routes were left in place.", flush=True)


def verify_remote_access(root, remote):
    """Self-check private HTTPS routing. Does not replace a test from another device."""
    if not remote.get("enabled"):
        return
    hostname = connected_hostname(cli_json("status", "--json"))
    if hostname != remote["hostname"]:
        raise RuntimeError("Tailscale hostname changed. Rerun Enable Remote Access.command.")
    serve = cli_json("serve", "status", "--json")
    check_conflicts(serve, hostname)
    for port, target in TARGETS.items():
        if serve.get("Web", {}).get(f"{hostname}:{port}", {}).get("Handlers") != {"/": {"Proxy": target}}:
            raise RuntimeError("Private proxy configuration is missing. Rerun Enable Remote Access.command.")
    with urlopen(remote["ui_url"] + "/health", timeout=30) as response:
        health = json.load(response)
    if not health.get("status"):
        raise RuntimeError("Open WebUI's private HTTPS health check failed.")
    root = Path(root)
    probe = root / "control/media" / ("remote-check-" + uuid.uuid4().hex + ".png")
    content = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
    try:
        probe.write_bytes(content)
        with urlopen(remote["media_url"] + "/media/" + probe.name, timeout=30) as response:
            if response.read() != content:
                raise RuntimeError("Generated-media HTTPS routing returned different content.")
        for path in ("/v1/models", "/health", "/media/../config.json"):
            try:
                with urlopen(remote["media_url"] + path, timeout=30):
                    raise RuntimeError("Media-only HTTPS exposed an unexpected endpoint.")
            except HTTPError as error:
                if error.code != 404:
                    raise RuntimeError("Unexpected media-only endpoint response.") from error
        atomic_json(root / "remote-acceptance-report.json", {
            "checked_at": time.time(), "status": "passed", "ui_url": remote["ui_url"],
            "media_url": remote["media_url"], "scope": "Mac-side HTTPS and media isolation checks",
            "other_device_browser_test": "pending"})
    finally:
        probe.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    try:
        disable(args.root) if args.disable else configure(args.root)
    except (Exception, KeyboardInterrupt) as error:
        print("Remote setup stopped:", error, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
