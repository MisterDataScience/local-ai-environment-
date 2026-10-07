"""Apply mode budgets through pinned WebUI's native API, without a summary loop."""
import json
import copy
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

BASE = 'http://127.0.0.1:8081'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_api(path, payload=None, token=None):
    # The URL is fixed; never inherit a proxy or follow a credential-bearing redirect.
    if path not in {'/api/v1/auths/signin', '/api/v1/configs/import',
                    '/api/v1/configs/namespace/chat', '/api/v1/configs/namespace/task'}:
        raise ValueError('Unsupported context settings endpoint')
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(
                Request(BASE + path, data=data, headers=headers), timeout=3) as response:
            value = response.read(4_000_001)
            if len(value) > 4_000_000:
                raise RuntimeError('Context settings response exceeded its size limit')
            return json.loads(value)
    except HTTPError as error:
        # Do not log response bodies or auth/session/account values.
        raise RuntimeError('Context settings API returned HTTP ' + str(error.code)) from None


class ContextSettings:
    def __init__(self):
        self.token = None
        self.applied = None

    def sync(self, policy):
        if policy == self.applied:
            return False
        try:
            if not self.token:
                # The bundled WebUI is explicitly single-user with WEBUI_AUTH=False.
                # Its native signin creates/reuses that user without a new password.
                auth = local_api('/api/v1/auths/signin', {'email': 'admin@localhost', 'password': ''})
                self.token = auth.get('token')
                if not isinstance(self.token, str) or not self.token:
                    raise RuntimeError('Local single-user WebUI session unavailable')
            task = local_api('/api/v1/configs/namespace/task', token=self.token)
            params = task.get('task.model.params') or {}
            if not isinstance(params, dict):
                raise RuntimeError('Invalid native task-model settings')
            updates = {'chat.context_compaction.enable': True,
                       'chat.context_compaction.token_threshold': policy['threshold'],
                       'chat.context_compaction.token_cap': policy['threshold'],
                       'chat.context_compaction.model': '',
                       'task.model.params': dict(params, max_tokens=policy['summary_tokens'])}
            local_api('/api/v1/configs/import', {'config': updates}, self.token)
            confirmed = local_api('/api/v1/configs/namespace/chat', token=self.token)
            if any(confirmed.get(k) != v for k, v in updates.items() if k.startswith('chat.')):
                raise RuntimeError('Native context settings did not take effect')
            self.applied = copy.deepcopy(policy)
            return True
        except Exception:
            # Expired sessions recover on the supervisor's next tick. Never
            # claim the mode's compaction settings applied after a failed update.
            self.token = None
            raise
