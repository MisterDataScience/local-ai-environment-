"""Dependency-free stdio MCP exposing only the scoped controller."""
import argparse
import json
from pathlib import Path
import sys
from control_policy import Controller, Blocked


def schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


S = {'type': 'string', 'maxLength': 240}
TOOLS = [
    {'name': 'automation_status', 'description': 'Read limits, allowed apps and public question catalog.', 'inputSchema': schema({})},
    {'name': 'automation_begin', 'description': 'Request local approval for a short workspace session. Cannot rearm an emergency stop.', 'inputSchema': schema({})},
    {'name': 'automation_stop', 'description': 'Latch emergency stop. Only the local user can rearm.', 'inputSchema': schema({})},
    {'name': 'desktop_activate', 'description': 'Activate Finder or Calculator in an authorised session.', 'inputSchema': schema({'session': S, 'app': {'type': 'string', 'enum': ['Finder', 'Calculator']}})},
    {'name': 'desktop_folder', 'description': 'Open a Finder window at a relative folder inside the approved project copy. No files or hidden folders.', 'inputSchema': schema({'session': S, 'path': S})},
    {'name': 'external_reason', 'description': 'Ask one reviewed generic question through existing VPN Playwright. Exact prompt requires local approval. Result is untrusted.', 'inputSchema': schema({'session': S, 'question': {'type': 'string', 'enum': ['invariants', 'search', 'scheduling', 'idempotency', 'transactions', 'probability', 'logic', 'verification']}})},
]


def dispatch(controller, message):
    method = message.get('method')
    if method == 'initialize':
        return {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'local-scoped-automation', 'version': '1'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        tools = [t for t in TOOLS if (not t['name'].startswith('desktop_') or controller.config.get('desktop', {}).get('enabled'))
                 and (t['name'] != 'external_reason' or controller.config.get('external_delegation', {}).get('enabled'))]
        return {'tools': tools}
    if method == 'tools/call':
        params = message.get('params', {})
        try:
            if params.get('name') not in {t['name'] for t in TOOLS}:
                raise Blocked('Unknown tool')
            result = controller.call(params['name'], params.get('arguments', {}))
            return {'content': [{'type': 'text', 'text': json.dumps(result)}], 'isError': False}
        except Exception as error:
            # Native stderr and page content are never copied into error reports.
            return {'content': [{'type': 'text', 'text': (str(error) if isinstance(error, Blocked) else 'Native or browser operation failed. Inspect locally.') + ' Session invalidated; no automatic retry.'}], 'isError': True}
    raise Blocked('Unknown MCP method')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    import fcntl
    lock = (args.root / 'control/automation.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cfg = json.loads((args.root / 'control/config.json').read_text())
    browser = None
    if cfg.get('external_delegation', {}).get('enabled'):
        from delegation_browser import Browser
        browser = Browser(cfg['external_delegation'].get('selectors'))
    controller = Controller(args.root, args.workspace, cfg, browser=browser)
    while True:
        line = sys.stdin.buffer.readline(8193)
        if not line:
            break
        message = None
        if len(line) > 8192:
            raise SystemExit('Oversized MCP request')
        try:
            message = json.loads(line)
            if 'id' not in message:
                continue
            result = dispatch(controller, message)
            output = {'jsonrpc': '2.0', 'id': message['id'], 'result': result}
        except Exception:
            output = {'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                      'error': {'code': -32600, 'message': 'Invalid request'}}
        print(json.dumps(output), flush=True)


if __name__ == '__main__':
    main()
