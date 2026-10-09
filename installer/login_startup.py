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
import tempfile

LABEL = "local.local-ai.start-at-login"


def launch_agent(root):
    root = Path(root).expanduser().resolve(strict=True)
    python = root / "control/.venv/bin/python"
    supervisor = root / "control/runtime.py"
    if not python.is_file() or not supervisor.is_file():
        raise RuntimeError("LOCAL AI installation is incomplete; rerun installer")
    return {"Label": LABEL, "ProgramArguments": [str(python), str(supervisor), '--background'],
            "WorkingDirectory": str(root / "control"),
            "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 60,
            "StandardOutPath": str(root / "logs/login-start.log"),
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
        changed = False
        if path.exists():
            existing = plistlib.loads(path.read_bytes())
            previous = dict(payload, ProgramArguments=payload['ProgramArguments'][:-1])
            if existing not in (payload, previous):
                raise RuntimeError('Existing LaunchAgent differs from this installation; do not overwrite')
            changed = existing != payload
        if not path.exists() or changed:
            data = plistlib.dumps(payload, sort_keys=True)
            fd, name = tempfile.mkstemp(prefix='.local-ai-login-', dir=agent_dir)
            temporary = Path(name)
            try:
                with os.fdopen(fd, 'wb') as file:
                    file.write(data)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        loaded = subprocess.run(['/bin/launchctl', 'print', f'gui/{uid}/{LABEL}'], capture_output=True, text=True)
        if loaded.returncode == 0:
            if not changed:
                print('Login-time starter is already registered.')
                return
            subprocess.run(['/bin/launchctl', 'bootout', f'gui/{uid}/{LABEL}'], capture_output=True, check=True)
        result = subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{uid}", str(path)],
                                capture_output=True, text=True)
        if result.returncode and "already bootstrapped" not in result.stderr.lower() and "service already loaded" not in result.stderr.lower():
            raise RuntimeError("launchctl bootstrap failed: " + result.stderr[:400])
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

