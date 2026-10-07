"""Configure optional Yandex reverse-image search credentials locally."""
import argparse
import fcntl
import getpass
import json
import os
from pathlib import Path

PROXY_URL = "http://127.0.0.1:8888"


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".new")
    with open(temporary, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump(value, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    path.chmod(0o600)


def configure(root, disable=False):
    lock = (root / ".runtime.lock").open("a")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Stop Local AI before changing reverse-image-search settings.")

        path = root / "control/config.json"
        config = json.loads(path.read_text())
        web = config.get("web", {})
        if disable:
            config.setdefault("reverse_image", {})["enabled"] = False
            save(path, config)
            print("Reverse image search disabled. Restart Local AI to apply.")
            return

        if not web.get("enabled") or web.get("proxy_url") != PROXY_URL:
            raise RuntimeError("Enable Web Access first. Reverse image search requires the installer-managed VPN proxy.")

        folder_id = input("Yandex Cloud folder ID: ").strip()
        api_key = getpass.getpass("Yandex Search API key: ").strip()
        if not folder_id or len(folder_id) > 256 or any(ord(c) < 33 for c in folder_id):
            raise ValueError("Invalid Yandex Cloud folder ID.")
        if not api_key or len(api_key) > 2048 or any(ord(c) < 33 for c in api_key):
            raise ValueError("Invalid Yandex Search API key.")

        config["reverse_image"] = {
            "enabled": True,
            "provider": "yandex",
            "folder_id": folder_id,
            "api_key": api_key,
        }
        save(path, config)
        print("Reverse image search configured.")
        print("Only an explicit reverse-image tool call sends data to Yandex.")
        print("The tool creates a metadata-free derivative and requires the loopback VPN proxy; proxy failure blocks the request.")
        print("Restart Local AI to apply.")
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    configure(args.root.expanduser().resolve(), args.disable)


if __name__ == "__main__":
    main()
