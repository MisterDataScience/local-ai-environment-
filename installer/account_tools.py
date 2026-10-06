"""Configure GitHub's official remote MCP server, with no custom GitHub agent."""
import argparse
import getpass
import json
import os
from pathlib import Path
import stat
import tempfile

URL = 'https://api.githubcopilot.com/mcp/'
# Intentional allowlist: no merge, deletion, account or repository administration.
TOOLS = 'get_me,get_file_contents,search_repositories,search_code,list_branches,list_commits,create_branch,create_or_update_file,push_files,issue_read,issue_write,add_issue_comment,pull_request_read,create_pull_request'


def connection(root):
    path = root / 'secrets/github-token'
    if path.is_symlink():
        raise ValueError('GitHub credential must not be a symlink.')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r') as f:
        s = os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_mode & 0o077 or s.st_uid != os.getuid():
            raise ValueError('GitHub credential must be owned by this user with mode 0600.')
        token = f.read(513).strip()
    if not token or len(token) > 512 or any(c.isspace() for c in token):
        raise ValueError('Invalid GitHub credential.')
    return {'type': 'mcp', 'url': URL, 'auth_type': 'bearer', 'key': token,
        'headers': {'X-MCP-Tools': TOOLS}, 'config': {'enable': True},
        'info': {'id': 'local-ai-github', 'name': 'GitHub', 'description': 'Selected GitHub repositories and approved changes'}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    from common import PORTS, port_open
    from workspace_setup import save_config
    if any(port_open(port) for port in PORTS.values()):
        raise SystemExit('Stop Local AI before configuring GitHub.')
    if not os.isatty(0):
        raise SystemExit('Run this helper in Terminal. Credentials are never accepted via arguments or redirected input.')
    print('Create a fine-grained GitHub personal access token for only the repositories you choose.')
    print('For writes: Contents, Issues and Pull requests read/write; Metadata read. Set an expiry.')
    print('https://github.com/settings/personal-access-tokens/new')
    print('This API credential is separate from your vault password. It is stored locally with mode 0600, outside iCloud.')
    print('Open WebUI receives it for authentication; the model does not. No Keychain is used.')
    token = getpass.getpass('GitHub token (blank to leave unchanged): ').strip()
    if not token:
        return
    if len(token) > 512 or any(c.isspace() for c in token):
        raise ValueError('Invalid token.')
    secrets = root / 'secrets'
    if secrets.is_symlink():
        raise ValueError('Secrets directory must not be a symlink.')
    secrets.mkdir(mode=0o700, exist_ok=True)
    secrets.chmod(0o700)
    fd, name = tempfile.mkstemp(dir=secrets, prefix='.github-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(token)
        os.replace(name, secrets / 'github-token')
    finally:
        if os.path.exists(name):
            os.unlink(name)
    config = json.loads((root / 'control/config.json').read_text())
    config['account_tools'] = {'github': True}
    save_config(root, config)
    print('Connection configured, not yet authenticated/tested. Restart Local AI and enable GitHub in chat Integrations.')
    print('Use Ask for approval. Verify a read, a DENIED write, then an approved write in a test repository.')
    print('Approval defaults can be overridden in the UI; this is not a separate server-side approval gate.')


if __name__ == '__main__':
    main()
