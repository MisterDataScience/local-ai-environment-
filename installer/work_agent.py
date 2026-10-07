"""Install and launch upstream OpenCode; no custom agent loop or agent tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

from common import http, stop_process, port_open

VERSION = '1.18.34'
URL = f'https://github.com/anomalyco/opencode/releases/download/v{VERSION}/opencode-darwin-arm64.zip'
SHA256 = '8522b70f545184b3a8d97c5ca4f814093b2476d72aebfda8c48bcd072ec31d1b'
SKIP = {'.git', '.opencode', '.claude', '.agents', '.venv', 'venv', 'node_modules',
        '__pycache__', '.ssh', '.aws', 'secrets', 'opencode.json', 'opencode.jsonc',
        'AGENTS.md', 'CLAUDE.md', '.mcp.json'}


def install(root, download, run):
    target = root / 'tools/opencode' / VERSION
    binary = target / 'opencode'
    if binary.is_file():
        run([binary, '--version'])
        return binary
    archive = root / 'downloads' / f'opencode-{VERSION}-darwin-arm64.zip'
    download(URL, archive, SHA256)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('OpenCode archive checksum mismatch')
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        members = [i for i in zipped.infolist() if Path(i.filename).name == 'opencode' and not i.is_dir()]
        if len(members) != 1 or stat.S_ISLNK(members[0].external_attr >> 16):
            raise ValueError('Unexpected OpenCode release archive')
        # Extract the binary only; never extract paths supplied by the archive.
        with zipped.open(members[0]) as source, binary.with_suffix('.partial').open('wb') as out:
            shutil.copyfileobj(source, out)
    binary.with_suffix('.partial').chmod(0o755)
    binary.with_suffix('.partial').replace(binary)
    run([binary, '--version'])
    return binary


def copy_project(source, destination, max_bytes=256*1024*1024):
    """Copy selected source without repo hooks/config, credentials or symlinks."""
    if source.is_symlink() or source.resolve() != source.absolute() or not source.is_dir():
        raise ValueError('Select a real project folder without symlink ancestors')
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('Select a project outside the Local AI agent workspace')
    total, files = 0, 0
    def walk(src, dest):
        nonlocal total, files
        dest.mkdir(mode=0o700)
        for p in sorted(src.iterdir()):
            if p.name in SKIP or p.name.startswith('.env') or p.suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}:
                continue
            info = p.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ValueError('Project contains a symlink; remove it from the selected copy: ' + p.name)
            if stat.S_ISDIR(info.st_mode):
                walk(p, dest / p.name)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total += info.st_size
                files += 1
                if total > max_bytes or files > 10000:
                    raise ValueError('Project exceeds 256 MiB or 10,000 files. Select a smaller project.')
                fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as inp, (dest / p.name).open('xb') as out:
                    if not stat.S_ISREG(os.fstat(inp.fileno()).st_mode):
                        raise ValueError('Project changed during copy')
                    shutil.copyfileobj(inp, out)
                (dest / p.name).chmod(0o700 if info.st_mode & 0o111 else 0o600)
            else:
                raise ValueError('Special or hard-linked project files are not supported')
    try:
        walk(source, destination)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def configuration(config, identifiers, mode='normal'):
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'payload'))
    from text_models import configured_text_models, output_ceiling
    presets = configured_text_models(config)
    models = {key: {'name': presets[key]['name'], 'limit': {
        'context': presets[key]['num_ctx'], 'output': output_ceiling(mode, presets[key]),
        'input': presets[key]['num_ctx'] - output_ceiling(mode, presets[key])}}
        for key in identifiers if key in presets}
    if not models:
        raise ValueError('No eligible local model for the work agent')
    preferred = 'local-ai' if 'local-ai' in models else next(iter(models))
    reserved = min(2048, min(m['limit']['context'] for m in models.values()) // 4)
    return {'$schema': 'https://opencode.ai/config.json', 'autoupdate': False,
            'share': 'disabled', 'enabled_providers': ['local-ai-gateway'],
            'model': 'local-ai-gateway/' + preferred, 'small_model': 'local-ai-gateway/' + preferred,
            'provider': {'local-ai-gateway': {'npm': '@ai-sdk/openai-compatible',
                'name': 'Local AI gateway', 'options': {'baseURL': 'http://127.0.0.1:8001/v1',
                'apiKey': '{env:LOCAL_AI_GATEWAY_KEY}', 'timeout': 1900000}, 'models': models}},
            'default_agent': 'plan', 'compaction': {'auto': True, 'prune': True, 'reserved': reserved},
            'permission': {'*': 'ask', 'read': {'*': 'allow', '*.env': 'deny', '*.env.*': 'deny'},
                'glob': 'allow', 'grep': 'allow', 'edit': 'ask', 'bash': 'ask',
                'external_directory': 'deny', 'webfetch': 'deny', 'websearch': 'deny', 'task': 'deny'},
            'tools': {'webfetch': False, 'websearch': False, 'task': False, 'lsp': False},
            'lsp': False, 'formatter': False,
            'agent': {'build': {'steps': 12}, 'plan': {'steps': 8}}}


def environment(root, config, settings):
    # Do not inherit cloud-provider keys, GitHub credentials or an existing
    # OpenCode configuration. Keep HOME unchanged; XDG separates agent state.
    allowed = {'HOME', 'PATH', 'TERM', 'COLORTERM', 'LANG', 'LC_ALL', 'TMPDIR', 'USER', 'SHELL'}
    env = {k: v for k, v in os.environ.items() if k in allowed}
    state = root / 'work-agent/state'
    for kind in ('config', 'data', 'cache', 'state'):
        p = state / kind
        p.mkdir(parents=True, exist_ok=True, mode=0o700)
        env['XDG_' + kind.upper() + '_HOME'] = str(p)
    env.update(LOCAL_AI_GATEWAY_KEY=config['api_key'],
               OPENCODE_CONFIG_CONTENT=json.dumps(settings), OPENCODE_DISABLE_PROJECT_CONFIG='true',
               OPENCODE_DISABLE_AUTOUPDATE='true', OPENCODE_DISABLE_MODELS_FETCH='true')
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--project', type=Path)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    config = json.loads((root / 'control/config.json').read_text())
    base, key = 'http://127.0.0.1:8001', config['api_key']
    status = http(base + '/control/mode', key=key)
    if status['mode'] == 'gaming' or status['transitioning'] or status['error']:
        raise RuntimeError('Select Normal or Max in AI Modes and wait for Ready before starting work.')
    if port_open(4096):
        raise RuntimeError('Port 4096 is occupied. Close the other work agent first.')
    models = http(base + '/v1/models', key=key)['data']
    settings = configuration(config, [m['id'] for m in models], status['mode'])
    binary = root / 'tools/opencode' / VERSION / 'opencode'
    if not binary.is_file():
        raise RuntimeError('OpenCode is missing. Rerun the Local AI installer.')
    sessions = root / 'work-agent/projects'
    sessions.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not args.project:
        value = input('Project folder to COPY, or Enter for a new empty project: ').strip()
        args.project = Path(value).expanduser() if value else None
    project = sessions / uuid.uuid4().hex
    if args.project:
        copy_project(args.project.absolute(), project)
    else:
        project.mkdir(mode=0o700)
    env = environment(root, config, settings)
    # A new repository has no source hooks, remotes or credential helpers.
    git_env = dict(env, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'init', '-q', str(project)], env=git_env, check=True)
    subprocess.run(['git', '-C', str(project), '-c', 'core.hooksPath=/dev/null', 'add', '--all'], env=git_env, check=True)
    subprocess.run(['git', '-C', str(project), '-c', 'core.hooksPath=/dev/null',
                    '-c', 'user.name=Local AI', '-c', 'user.email=local-ai@localhost',
                    '-c', 'commit.gpgsign=false', 'commit', '-q', '--allow-empty',
                    '-m', 'Imported project baseline'], env=git_env, check=True)
    print('OpenCode project copy:', project, flush=True)
    print('Starts in Plan. Switch to Build to edit; approve each edit/command in OpenCode.', flush=True)
    print('Work and session history are LOCAL, outside the vault. This is not an OS sandbox.', flush=True)
    git_env['OPENCODE_SERVER_PASSWORD'] = secrets.token_urlsafe(24)
    git_env['OPENCODE_SERVER_USERNAME'] = 'opencode'
    print('OpenCode: http://127.0.0.1:4096  Username: opencode', flush=True)
    print('Session password:', git_env['OPENCODE_SERVER_PASSWORD'], flush=True)
    process = subprocess.Popen([str(binary), 'web', '--hostname', '127.0.0.1', '--port', '4096'],
                               cwd=project, env=git_env, start_new_session=True)
    try:
        while process.poll() is None:
            time.sleep(1)
            status = http(base + '/control/mode', key=key, timeout=3)
            if status['mode'] == 'gaming' or status['transitioning'] or status['error']:
                print('Mode changed or backend blocked. Stopping the work agent.', flush=True)
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop_process(process, timeout=10)
        print('Project preserved at:', project)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Work agent stopped: ' + str(error))

