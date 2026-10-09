"""Bounded client of the EXISTING VPN Playwright MCP; no browser subprocess."""
import json
import time
from urllib.request import Request, ProxyHandler, build_opener, HTTPRedirectHandler
from control_policy import Blocked

URL = 'http://127.0.0.1:8931/mcp'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Blocked('MCP redirects are prohibited')


class MCP:
    def __init__(self):
        self.session = None
        self.counter = 0
        self.code_tool = None
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, params, notify=False):
        self.counter += 1
        message = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notify:
            message['id'] = self.counter
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.session:
            headers['MCP-Protocol-Version'] = '2025-06-18'
            headers['Mcp-Session-Id'] = self.session
        request = Request(URL, data=json.dumps(message).encode(), headers=headers, method='POST')
        with self.opener.open(request, timeout=10) as response:
            self.session = response.headers.get('Mcp-Session-Id', self.session)
            raw = response.read(131073)
        if len(raw) > 131072:
            raise Blocked('MCP response too large')
        if notify:
            return None
        for line in raw.decode().splitlines():
            candidate = line.removeprefix('data: ').strip()
            if not candidate.startswith('{'):
                continue
            value = json.loads(candidate)
            if value.get('id') == self.counter:
                if 'error' in value or 'result' not in value:
                    raise Blocked('MCP operation failed; no retry')
                return value['result']
        raise Blocked('Invalid MCP response')

    def connect(self):
        result = self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'local-approved-delegation', 'version': '1'}})
        if not result.get('serverInfo'):
            raise Blocked('Browser MCP handshake failed')
        self.request('notifications/initialized', {}, notify=True)
        names = {t['name'] for t in self.request('tools/list', {}).get('tools', [])}
        self.code_tool = next((name for name in ('browser_run_code_unsafe', 'browser_run_code') if name in names), None)
        if self.code_tool is None:
            raise Blocked('Pinned browser does not support the required tool')

    def code(self, code):
        result = self.request('tools/call', {'name': self.code_tool, 'arguments': {'code': code}})
        if result.get('isError'):
            raise Blocked('Browser operation failed; no retry')
        # Playwright MCP returns the function result under its Result heading.
        # No snapshot, console or network-request content is passed to the model.
        for block in result.get('content', []):
            if block.get('type') != 'text':
                continue
            text = block.get('text', '')
            if '### Result\n' not in text:
                continue
            body = text.split('### Result\n', 1)[1].split('\n### ', 1)[0].strip()
            if body.startswith('```'):
                body = body.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            try:
                value = json.loads(body)
                if isinstance(value, str):
                    value = json.loads(value)
                if isinstance(value, dict):
                    return value
            except (ValueError, TypeError):
                pass
        raise Blocked('Unknown browser response format; inspect locally, no fallback')

    def close(self):
        if self.session:
            request = Request(URL, headers={'Mcp-Session-Id': self.session}, method='DELETE')
            try:
                with self.opener.open(request, timeout=3):
                    pass
            except Exception:
                pass
            self.session = None


class Browser:
    def __init__(self, selectors, client_factory=MCP, clock=time.monotonic, wait=time.sleep):
        if not isinstance(selectors, dict) or set(selectors) != {'input', 'submit', 'response', 'busy', 'challenge'}:
            raise Blocked('Locally verified DeepSeek selectors are required')
        if any(not isinstance(v, str) or not v or len(v) > 200 for v in selectors.values()):
            raise Blocked('Invalid selector configuration')
        self.selectors = selectors
        self.client_factory = client_factory
        self.clock = clock
        self.wait = wait

    def reason(self, prompt, check):
        # Only fixed question strings from Controller enter this adapter.
        from control_policy import QUESTIONS
        if prompt not in QUESTIONS.values():
            raise Blocked('Prompt outside the reviewed catalog')
        check()
        client = self.client_factory()
        deadline = self.clock() + 90
        s = json.dumps(self.selectors)
        # All JS is host-owned. Selector/prompt values are JSON literals, never source.
        guard = '''const s = SELECTORS;
            if (new URL(page.url()).origin !== 'https://chat.deepseek.com') throw new Error('Unexpected origin');
            if (await page.locator(s.challenge).count() && await page.locator(s.challenge).first().isVisible()) throw new Error('Challenge; manual action required');
        '''.replace('SELECTORS', s)
        try:
            client.connect()
            check()
            initial = client.code('async (page) => { await page.goto("https://chat.deepseek.com/", {timeout: 8000, waitUntil: "domcontentloaded"});'
                + guard + '''if (await page.locator(s.response).count() !== 0) throw new Error('Fresh chat required');
                if (await page.locator(s.input).count() !== 1 || await page.locator(s.submit).count() !== 1) throw new Error('Verify selectors/login locally');
                return {ready:true}; }''')
            if initial != {'ready': True}:
                raise Blocked('Fresh authorised chat could not be verified')
            check()
            filled = client.code('async (page) => {' + guard
                + 'await page.locator(s.input).fill(' + json.dumps(prompt) + ', {timeout:3000});'
                + 'return {matches: (await page.locator(s.input).inputValue()) === ' + json.dumps(prompt) + '}; }')
            if filled != {'matches': True}:
                raise Blocked('Outgoing prompt changed before submission')
            check()
            # One submission. A transport failure after this call has unknown outcome.
            # Never resubmit on failure; session is latched by the controller.
            sent = client.code('async (page) => {' + guard
                + 'if (await page.locator(s.input).inputValue() !== ' + json.dumps(prompt) + ') throw new Error("Prompt mismatch");'
                + 'if (await page.locator(s.response).count() !== 0) throw new Error("Chat changed");'
                + 'await page.locator(s.submit).click({timeout:3000}); return {sent:true}; }')
            if sent != {'sent': True}:
                raise Blocked('Submission outcome unknown; do not retry')
            for _ in range(40):
                check()
                if self.clock() >= deadline:
                    raise Blocked('Response timeout; do not resubmit')
                value = client.code('async (page) => {' + guard + '''
                    const responses = page.locator(s.response);
                    const busy = page.locator(s.busy);
                    if (await busy.count() && await busy.first().isVisible()) return {pending:true};
                    if (await responses.count() !== 1) return {pending:true};
                    const text = await responses.first().innerText({timeout:3000});
                    if (!text.trim()) return {pending:true};
                    if (text.length > 10000) throw new Error('Response exceeds limit');
                    return {response:text}; }''')
                if set(value) == {'response'} and isinstance(value['response'], str) and 0 < len(value['response']) <= 10000:
                    check()
                    return value['response']
                if value != {'pending': True}:
                    raise Blocked('Unexpected response')
                # Short polling is only retrieval, never another submission.
                self.wait(1)
            raise Blocked('Response poll limit; do not resubmit')
        finally:
            client.close()
