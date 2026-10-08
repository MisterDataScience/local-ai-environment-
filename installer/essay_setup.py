"""Explicit local draft selection; submit text without slash-command expansion."""
import base64
import json
from pathlib import Path
from urllib.request import Request, urlopen


def read_draft(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {'.md', '.txt'}:
        raise ValueError('Select a regular UTF-8 .md or .txt essay draft')
    if path.stat().st_size > 120000:
        raise ValueError('Draft exceeds the 120 KB submission limit; select a scoped section')
    draft = path.read_bytes().decode('utf-8')
    if not draft.strip() or len(draft) > 30000:
        raise ValueError('Use a nonempty draft of at most 30,000 characters; the handoff limit is smaller')
    return {'draft': draft, 'author_request': 'Copyedit this essay using my installed style profile.',
            'constraints': '', 'source_material': '', 'reorder': 'none', 'randomiser': False}


def submit(password, request):
    token = base64.b64encode(('opencode:' + password).encode()).decode()
    def native(path, body):
        req = Request('http://127.0.0.1:4096' + path, data=json.dumps(body).encode(),
                      headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    session = native('/session', {'title': 'Essay copyedit: author review required'})['id']
    native('/session/' + session + '/prompt_async', {'agent': 'plan', 'parts': [
        {'type': 'text', 'text': 'ESSAY_EDIT\n' + json.dumps(request, ensure_ascii=False)}]})
    return session


def connection_file(root):
    return root / 'work-agent/state/native-session.json'


def publish_connection(root, password):
    import os
    path = connection_file(root)
    # Private local launcher credential, outside model project copies.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump({'pid': os.getpid(), 'password': password}, out)


def clear_connection(root, password):
    path = connection_file(root)
    try:
        if not path.is_symlink() and json.loads(path.read_text()).get('password') == password:
            path.unlink()
    except (OSError, ValueError):
        pass


def attach(root, request):
    import os
    import stat
    path = connection_file(root)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('Existing work-agent connection file is not private')
    value = json.loads(path.read_text())
    if type(value.get('pid')) is not int or value['pid'] <= 0:
        raise RuntimeError('Invalid work-agent connection record')
    os.kill(value['pid'], 0)
    if not isinstance(value.get('password'), str) or not value['password']:
        raise RuntimeError('Invalid work-agent credential')
    return submit(value['password'], request)
