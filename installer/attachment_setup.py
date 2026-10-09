"""Register and verify our global filter using the pinned native WebUI API."""
import json
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from context_settings import NoRedirect

ID = 'local_ai_attachments'


def api(path, payload=None, token=None):
    if path != '/api/v1/auths/signin' and not path.startswith('/api/v1/functions/'):
        raise ValueError('Unsupported attachment setup endpoint')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None if payload is None else json.dumps(payload).encode()
    with build_opener(ProxyHandler({}), NoRedirect()).open(Request('http://127.0.0.1:8081' + path, data=data, headers=headers), timeout=10) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise RuntimeError('Attachment setup response too large')
        return json.loads(raw)


def configure(root):
    content = (root / 'control/webui_attachments_filter.py').read_text()
    token = api('/api/v1/auths/signin', {'email': 'admin@localhost', 'password': ''})['token']
    functions = api('/api/v1/functions/', token=token)
    existing = next((f for f in functions if f['id'] == ID), None)
    form = {'id': ID, 'name': 'Local AI attachments', 'content': content, 'meta': {'description': 'Local images and native PDF/OCR'}}
    if existing is None:
        api('/api/v1/functions/create', form, token)
    else:
        actual = api('/api/v1/functions/id/' + ID, token=token)
        if actual['content'] != content:
            api('/api/v1/functions/id/' + ID + '/update', form, token)
    actual = api('/api/v1/functions/id/' + ID, token=token)
    if not actual.get('is_active'):
        api('/api/v1/functions/id/' + ID + '/toggle', {}, token)
    if not actual.get('is_global'):
        api('/api/v1/functions/id/' + ID + '/toggle/global', {}, token)
    confirmed = api('/api/v1/functions/id/' + ID, token=token)
    if not confirmed.get('is_active') or not confirmed.get('is_global') or confirmed['content'] != content:
        raise RuntimeError('Chat attachment filter registration was not confirmed')
