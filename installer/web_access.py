"""Optional local Docker Compose VPN web stack. Credentials stay on the Mac."""
import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
from urllib.request import Request, build_opener, ProxyHandler

IMAGES = {"vpn": "qmcgaw/gluetun:v3.41.0", "search": "searxng/searxng:latest", "reader": "python:3.12-alpine"}


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".new")
    with open(temporary, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump(value, output, indent=2)
        output.write("\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def run(command, **kwargs):
    return subprocess.run([str(p) for p in command], check=True, **kwargs)


def docker_command():
    binary = shutil.which("docker")
    if not binary and Path("/Applications/Docker.app/Contents/Resources/bin/docker").is_file():
        binary = "/Applications/Docker.app/Contents/Resources/bin/docker"
    if not binary:
        raise RuntimeError("Install and open Docker Desktop for Apple Silicon once, then rerun this helper. "
                           "Download: https://docs.docker.com/desktop/setup/install/mac-install/")
    context = json.loads(run([binary, "context", "inspect"], capture_output=True, text=True, timeout=10).stdout)
    endpoint = context[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("unix://") or os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise RuntimeError("Use a local Docker context without DOCKER_HOST/DOCKER_CONTEXT overrides. Remote daemons are blocked.")
    run([binary, "info"], capture_output=True, timeout=15)
    run([binary, "compose", "version"], capture_output=True, timeout=10)
    return binary


def compose(root, *args, capture=False, timeout=300):
    project = "local-ai-web-" + hashlib.sha256(str(root).encode()).hexdigest()[:10]
    return run([docker_command(), "compose", "--project-name", project,
                "--file", root / "web/compose.json", *args], cwd=root / "web",
               capture_output=capture, text=True, timeout=timeout)


def specification(images):
    network = "service:vpn"
    return {"services": {
        "vpn": {"image": images["vpn"], "cap_add": ["NET_ADMIN"],
                "devices": ["/dev/net/tun:/dev/net/tun"], "env_file": ["vpn.env"],
                "environment": {"VPN_SERVICE_PROVIDER": "protonvpn", "VPN_TYPE": "wireguard",
                                "FREE_ONLY": "on", "FIREWALL": "on", "FIREWALL_INPUT_PORTS": "8090",
                                "VPN_PORT_FORWARDING": "off", "DNS_UPSTREAM_RESOLVER_TYPE": "dot",
                                "DNS_UPSTREAM_RESOLVERS": "cloudflare", "DNS_UPSTREAM_IPV6": "off"},
                "ports": ["127.0.0.1:8090:8090"], "mem_limit": "256m", "cpus": 0.5},
        "search": {"image": images["search"], "network_mode": network,
                   "depends_on": {"vpn": {"condition": "service_healthy"}},
                   "volumes": ["./settings.yml:/etc/searxng/settings.yml:ro", "./resolv.conf:/etc/resolv.conf:ro"],
                   "environment": {"SEARXNG_SETTINGS_PATH": "/etc/searxng/settings.yml",
                                   "FORCE_OWNERSHIP": "false", "GRANIAN_HOST": "127.0.0.1",
                                   "SEARXNG_PORT": "8080"},
                   "mem_limit": "512m", "cpus": 1},
        "reader": {"image": images["reader"], "network_mode": network,
                   "depends_on": {"vpn": {"condition": "service_healthy"}},
                   "command": ["python", "-B", "/app/service.py"], "user": "65532:65532",
                   "env_file": ["reader.env"], "volumes": ["./service.py:/app/service.py:ro",
                                                            "./resolv.conf:/etc/resolv.conf:ro"],
                   "read_only": True, "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                   "mem_limit": "128m", "cpus": 0.5}},
        "networks": {"default": {"enable_ipv6": False}}}


def status(root):
    config = json.loads((root / "control/config.json").read_text())
    key = config.get("web", {}).get("api_key", "")
    request = Request("http://127.0.0.1:8090/health", headers={"Authorization": "Bearer " + key})
    with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
        return json.load(response)


def start(root):
    # Recreate namespace-sharing clients whenever the VPN container is recreated.
    compose(root, "up", "--detach", "--force-recreate", "--pull", "never", timeout=180)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if status(root).get("status") == "ready":
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("VPN web service did not become ready. Chat remains local; web requests will be blocked.")


def configure(root):
    # A running gateway must not see half-written configuration.
    import fcntl
    runtime_lock = (root / ".runtime.lock").open("a")
    try:
        fcntl.flock(runtime_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        runtime_lock.close()
        raise RuntimeError("Stop Local AI before enabling web access.")
    try:
        binary = docker_command()
        web = root / "web"
        web.mkdir(mode=0o700, exist_ok=True)
        web.chmod(0o700)
        source = Path(__file__).resolve().parent / "web/service.py"
        if source.resolve() != (web / "service.py").resolve():
            shutil.copy2(source, web / "service.py")
        if not (web / "vpn.env").exists():
            print("Generate a WireGuard configuration for a FREE server at https://account.proton.me/u/0/vpn/WireGuard")
            print("Paste only its PrivateKey value below. It will not be displayed or sent to GitHub.")
            key = getpass.getpass("Proton WireGuard PrivateKey: ").strip()
            try:
                if len(base64.b64decode(key, validate=True)) != 32:
                    raise ValueError()
            except Exception:
                raise ValueError("Expected a base64-encoded 32-byte WireGuard private key.")
            with open(web / "vpn.env", "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
                output.write("WIREGUARD_PRIVATE_KEY=" + key + "\n")
        config_path = root / "control/config.json"
        config = json.loads(config_path.read_text())
        api_key = config.get("web", {}).get("api_key") or secrets.token_urlsafe(32)
        with open(web / "reader.env", "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
            output.write("WEB_API_KEY=" + api_key + "\n")
        (web / "reader.env").chmod(0o600)
        (web / "vpn.env").chmod(0o600)
        (web / "resolv.conf").write_text("nameserver 127.0.0.1\noptions timeout:2 attempts:2\n")
        # JSON is a valid YAML document. This avoids fragile YAML quoting for the secret.
        settings = {"use_default_settings": True, "server": {"secret_key": secrets.token_hex(32),
                    "limiter": False, "image_proxy": False}, "search": {"formats": ["json"]},
                    "outgoing": {"request_timeout": 10, "max_request_timeout": 15}}
        save(web / "settings.yml", settings)
        # Files must be readable by the unprivileged container users. Parent remains 0700 on host.
        (web / "settings.yml").chmod(0o644)
        lock_path = web / "images.json"
        if lock_path.exists():
            images = json.loads(lock_path.read_text())
        else:
            images = {}
            for name, image in IMAGES.items():
                run([binary, "pull", image], timeout=900)
                inspected = json.loads(run([binary, "image", "inspect", image], capture_output=True,
                                          text=True, timeout=30).stdout)[0]
                digests = inspected.get("RepoDigests", [])
                if not digests:
                    raise RuntimeError("Cannot record immutable container digest: " + image)
                images[name] = digests[0]
            save(lock_path, images)
        save(web / "compose.json", specification(images))
        backup = root / "control/config.before-web-access.json"
        if not backup.exists():
            save(backup, config)
        config["web"] = {"enabled": True, "url": "http://127.0.0.1:8090", "api_key": api_key}
        save(config_path, config)
        start(root)
        save(root / "web-acceptance-report.json", {"status": "vpn_service_ready", "images": images,
             "search_and_page_test": "pending", "vpn_drop_and_dns_leak_test": "pending"})
        print("VPN service ready. Use /search QUERY or /read https://example.org QUESTION in your chat.")
        print("Actual search/page and tunnel-drop checks are still required. See WEB-ACCESS.md.")
    finally:
        runtime_lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if args.disable:
        # Do not change other Docker services or the Mac's network routes.
        compose(root, "down")
        path = root / "control/config.json"
        config = json.loads(path.read_text())
        config.setdefault("web", {})["enabled"] = False
        save(path, config)
        print("Web access disabled. Restart Local AI to apply.")
    else:
        configure(root)


if __name__ == "__main__":
    main()
