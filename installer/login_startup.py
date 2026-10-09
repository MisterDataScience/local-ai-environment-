"""Configure a conservative login-time startup for the existing Local AI app.

LaunchAgent starts the existing user-facing supervisor after login. No root,
system service, background inference or sleeping-Mac wake bypass is installed.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess

LABEL = "local.local-ai.start-at-login"


def launch_agent(root):
    root = Path(root).expanduser().resolve(strict=True)
    app = Path.home() / "Applications/Local AI.app"
    owned = app / "Contents/local-ai-owner.txt"
    if not owned.is_file() or owned.read_text().strip() != str(root):
        raise RuntimeError("Owned Local AI.app is missing; rerun the installer")
    return {"Label": LABEL, "ProgramArguments": ["/usr/bin/open", "-a", str(app)],
            "RunAtLoad": True, "StandardOutPath": str(root / "logs/login-start.log"),
            "StandardErrorPath": str(root / "logs/login-start-error.log")}


def configure(root, enabled):
    root = Path(root).expanduser().resolve(strict=True)
    agent_dir = Path.home() / "Library/LaunchAgents"
    agent_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = agent_dir / (LABEL + ".plist")
    uid = os.getuid()
    if path.is_symlink():
        raise RuntimeError("LaunchAgent symlink refused")
    if enabled:
        payload = launch_agent(root)
        if path.exists():
            if plistlib.loads(path.read_bytes()) != payload:
                raise RuntimeError("Existing LaunchAgent differs; do not overwrite")
        else:
            data = plistlib.dumps(payload, sort_keys=True)
            temporary = path.with_suffix(".tmp")
            with temporary.open("xb") as file:
                file.write(data)
            temporary.chmod(0o600)
            temporary.replace(path)
        subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{uid}", str(path)],
                       capture_output=True, text=True, check=False)
        print("Login-time starter registered. Confirm launch behavior at next macOS login.")
    else:
        if not path.exists():
            print("No Local AI login agent exists.")
            return
        if plistlib.loads(path.read_bytes()).get("Label") != LABEL:
            raise RuntimeError("Unexpected LaunchAgent contents")
        subprocess.run(["/bin/launchctl", "bootout", f"gui/{uid}/{LABEL}"],
                       capture_output=True, text=True, check=False)
        path.unlink()
        print("Local AI login-time starter removed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    configure(args.root, not args.disable)


if __name__ == "__main__":
    main()
