"""Install the official, signed Apple Silicon Docker Desktop within Captain setup.

No package manager, shell pipe, disabled Gatekeeper or implicit license acceptance.
The user accepts Docker's terms in its own GUI, during the same installer run.
"""
import os
from pathlib import Path
import pwd
import re
import shlex
import subprocess
import time

APP = Path('/Applications/Docker.app')
URL = 'https://desktop.docker.com/mac/main/arm64/Docker.dmg'
TEAM = '9BNSXJN65R'


def run(command, **kwargs):
    return subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def verify(app):
    """Fail closed if existing or downloaded app is not signed by Docker Inc."""
    app = Path(app)
    if app.is_symlink() or not app.is_dir():
        raise RuntimeError('Expected a regular Docker Desktop application')
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)],
        timeout=90, capture_output=True)
    run(['/usr/sbin/spctl', '--assess', '--type', 'execute', str(app)],
        timeout=60, capture_output=True)
    result = run(['/usr/bin/codesign', '-d', '--verbose=4', str(app)],
                 timeout=30, capture_output=True, text=True)
    if f'TeamIdentifier={TEAM}' not in result.stderr:
        raise RuntimeError('Docker Desktop is not signed by the expected Docker Inc developer.')


def docker_binary():
    candidates = (APP / 'Contents/Resources/bin/docker',
                  Path.home() / '.docker/bin/docker',
                  Path('/usr/local/bin/docker'))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError('Docker Desktop CLI is missing after application installation.')


def ready(binary):
    import json
    result = run([binary, 'context', 'inspect'], capture_output=True, text=True, timeout=15)
    context = json.loads(result.stdout)
    endpoint = context[0]['Endpoints']['docker']['Host']
    if not endpoint.startswith('unix://') or os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise RuntimeError('Docker must use a local Unix socket, not a remote daemon.')
    run([binary, 'info'], capture_output=True, timeout=30)
    run([binary, 'compose', 'version'], capture_output=True, timeout=30)


def install(root, download, *, prompt=input, say=print, timeout=900):
    root = Path(root)
    if not APP.exists():
        image = root / 'cache/docker-desktop-arm64.dmg'
        download(URL, image)
        mount = root / 'cache/docker-desktop-mounted'
        mount.mkdir(mode=0o700, exist_ok=True)
        if any(mount.iterdir()):
            raise RuntimeError('Docker mount location is not empty; unmount the old image and retry')
        attached = False
        try:
            run(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', mount, image],
                capture_output=True, timeout=180)
            attached = True
            app = mount / 'Docker.app'
            verify(app)
            installer = app / 'Contents/MacOS/install'
            if not installer.is_file():
                raise RuntimeError('Official Docker installer executable is missing')
            say('Installing signed Docker Desktop. macOS may request administrator approval.')
            # Docker's official installer prompts for/records licensing separately.
            # Never add --accept-license without explicit owner consent.
            username = pwd.getpwuid(os.getuid()).pw_name
            command = shlex.join([str(installer), '--user=' + username])
            script = 'on run argv\n  do shell script (item 1 of argv) with administrator privileges\nend run'
            run(['/usr/bin/osascript', '-e', script, command], timeout=1200)
        finally:
            if attached:
                run(['/usr/bin/hdiutil', 'detach', mount], capture_output=True, timeout=90)
    verify(APP)
    say('Docker Desktop will open. Review and accept its licence in Docker itself.')
    run(['/usr/bin/open', '-a', str(APP)], timeout=30)
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            binary = docker_binary()
            ready(binary)
            say('Local Docker Engine and Compose are ready.')
            return binary
        except (OSError, RuntimeError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as error:
            last = error
        time.sleep(5)
    raise RuntimeError('Docker Desktop did not start its local Engine/Compose during installation: '
                       + str(last) + '. Complete Docker licence/permissions in the open app and rerun this installer.')
