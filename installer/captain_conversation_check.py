"""Check native Captain completion and resumption across automatic compaction.

Uses one new tool-denied session and the installed local model. It does not
qualify optional features or alter prior installation acceptance receipts.
"""
import argparse
import base64
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from feature_state import atomic_json


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def verify_native(root, *, native=None, model_id=None, startup_timeout=600, call_timeout=180):
    """Use a new, tool-denied session; never modify an existing conversation."""
    root = Path(root)
    report_path = root / 'logs/native-acceptance/conversation-repair-probe.json'
    report_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if report_path.is_symlink():
        raise RuntimeError('Unsafe conversation probe report path')
    report = {'status': 'running', 'stage': 'startup',
              'scope': 'One tool-denied session: completed replies stay stopped and a queued genuine request resumes across compaction; not full installation acceptance.',
              'thinking_configuration_changed': False, 'session_id': None, 'checks': {}}
    session_id = None
    def save():
        atomic_json(report_path, report)
    try:
        save()
        if native is None:
            control = root / 'control'
            config = json.loads((control / 'config.json').read_text())
            model_id = config['captain']['model_id']
            auth_path = control / 'captain-ui-auth.json'
            if auth_path.is_symlink():
                raise RuntimeError('Unsafe Captain credential path')
            auth = json.loads(auth_path.read_text())
            token = base64.b64encode((auth['username'] + ':' + auth['password']).encode()).decode()
            directory = root / 'work-agent/projects/captain-default'
            if directory.is_symlink() or not directory.is_dir():
                raise RuntimeError('Managed Captain project is unavailable for the probe')
            query = '?' + urlencode({'directory': str(directory)})
            opener = build_opener(ProxyHandler({}), NoRedirect())
            def native(path, body=None, *, timeout=call_timeout):
                request = Request('http://127.0.0.1:4096' + path + query,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'})
                try:
                    with opener.open(request, timeout=timeout) as response:
                        return json.load(response)
                except HTTPError as error:
                    raise RuntimeError('Captain probe API returned HTTP ' + str(error.code)) from None
        until = time.monotonic() + startup_timeout
        while True:
            try:
                active = native('/config', timeout=5)
                break
            except (URLError, TimeoutError, RuntimeError, OSError):
                if time.monotonic() >= until:
                    raise RuntimeError('Captain did not become ready for the conversation probe') from None
                time.sleep(2)
        report['stage'] = 'configuration'
        limits = active['provider']['local-ai-gateway']['models'][model_id]['limit']
        if not (0 < limits['output'] <= limits['context'] // 4
                and active['compaction']['reserved'] <= 512):
            raise RuntimeError('Captain is still using the old context budget')
        report.update(model_id=model_id, limits=limits, reserved=active['compaction']['reserved'])
        report['checks']['active_budget'] = True
        report['stage'] = 'completed_reply'
        save()
        session = native('/session', {'title': 'Conversation repair check',
            'permission': [{'permission': '*', 'pattern': '*', 'action': 'deny'}]})
        session_id = session['id']
        report['session_id'] = session_id
        response = native('/session/' + session_id + '/message', {
            'agent': 'plan', 'model': {'providerID': 'local-ai-gateway', 'modelID': model_id},
            'parts': [{'type': 'text', 'text': 'Reply exactly READY. This completes the test; there is no next step. Do not use tools.'}]})
        final = ''.join(part.get('text', '') for part in response.get('parts', []) if part.get('type') == 'text').strip()
        report['initial_reply'] = {'finish': response.get('info', {}).get('finish'),
            'final_text': final[:500], 'tokens': response.get('info', {}).get('tokens'),
            'has_error': bool(response.get('info', {}).get('error'))}
        if response.get('info', {}).get('error') or response.get('info', {}).get('finish') != 'stop' or final != 'READY':
            raise RuntimeError('Captain did not produce the expected completed test reply')
        report['checks']['completed_reply'] = True
        report['stage'] = 'automatic_compaction'
        save()
        for attempt in range(1, 3):
            report['compaction_attempt'] = attempt
            save()
            native('/session/' + session_id + '/summarize',
                   {'providerID': 'local-ai-gateway', 'modelID': model_id, 'auto': True})
            messages = native('/session/' + session_id + '/message')
            assistants = [message for message in messages if message['info']['role'] == 'assistant']
            normal = [message for message in assistants if not message['info'].get('summary')
                      and message['info'].get('agent') not in ('compaction', 'title', 'summary')]
            summaries = [message for message in assistants if message['info'].get('summary')]
            report['ordinary_reply_count'] = len(normal)
            report['summary_count'] = len(summaries)
            report.setdefault('observations', []).append({'attempt': attempt,
                'ordinary_reply_count': len(normal), 'summary_count': len(summaries),
                'assistants': [{'id': message['info']['id'], 'agent': message['info'].get('agent'),
                    'summary': bool(message['info'].get('summary')), 'finish': message['info'].get('finish'),
                    'has_error': bool(message['info'].get('error')), 'tokens': message['info'].get('tokens')}
                    for message in assistants]})
            if len(normal) != 1:
                raise RuntimeError('Automatic compaction generated an extra answer after completion')
            if any(message['info'].get('error') for message in assistants):
                raise RuntimeError('Native conversation probe contains an assistant error')
            if len(summaries) < attempt or any(not message['info'].get('finish') for message in summaries):
                raise RuntimeError('The forced native compaction did not complete')
            if any(part.get('type') == 'tool' or part.get('metadata', {}).get('compaction_continue')
                   for message in messages for part in message['parts']):
                raise RuntimeError('Completed test session attempted tools or synthetic continuation')
            report['checks']['completed_chat_stays_stopped_' + str(attempt)] = True
            report['ordinary_reply_count'] = len(normal)
            report['summary_count'] = len(summaries)
            save()
        # Persist a genuine new request without generating its answer yet. This
        # gives the native resume hook real unfinished work rather than a fake
        # assistant record or an injected continuation message.
        report['stage'] = 'unfinished_request'
        save()
        queued = native('/session/' + session_id + '/message', {
            'agent': 'plan', 'model': {'providerID': 'local-ai-gateway', 'modelID': model_id},
            'noReply': True, 'parts': [{'type': 'text', 'text':
                'Reply exactly DONE to this new request. Do not use tools or include maintenance summaries.'}]})
        report['queued_user_message_id'] = queued.get('info', {}).get('id') if isinstance(queued, dict) else None
        for attempt in (3, 4):
            report['compaction_attempt'] = attempt
            save()
            native('/session/' + session_id + '/summarize',
                   {'providerID': 'local-ai-gateway', 'modelID': model_id, 'auto': True})
            messages = native('/session/' + session_id + '/message')
            assistants = [message for message in messages if message['info']['role'] == 'assistant']
            normal = [message for message in assistants if not message['info'].get('summary')
                      and message['info'].get('agent') not in ('compaction', 'title', 'summary')]
            summaries = [message for message in assistants if message['info'].get('summary')]
            last_text = ''.join(part.get('text', '') for part in normal[-1]['parts']
                                if part.get('type') == 'text').strip() if normal else ''
            report['ordinary_reply_count'] = len(normal)
            report['summary_count'] = len(summaries)
            report.setdefault('observations', []).append({'attempt': attempt,
                'ordinary_reply_count': len(normal), 'summary_count': len(summaries), 'last_reply': last_text[:500],
                'last_summary': ''.join(part.get('text', '') for part in summaries[-1]['parts']
                    if part.get('type') == 'text')[:2000] if summaries else ''})
            if len(normal) != 2 or last_text != 'DONE' or normal[-1]['info'].get('finish') != 'stop':
                raise RuntimeError('The queued genuine request did not resume exactly once with its requested answer')
            if len(summaries) < attempt or any(message['info'].get('error') for message in assistants):
                raise RuntimeError('Native unfinished-request compaction failed')
            if any(part.get('type') == 'tool' for message in messages for part in message['parts']):
                raise RuntimeError('The tool-denied conversation probe attempted a tool')
            report['checks']['unfinished_request_resumes' if attempt == 3 else 'resumed_reply_stays_stopped'] = True
            save()
        report.update(status='passed', stage='complete')
    except Exception as error:
        report.update(status='failed', issue=str(error)[:700], error_type=type(error).__name__)
        if session_id and native:
            try:
                native('/session/' + session_id + '/abort', {}, timeout=5)
            except Exception:
                pass
    save()
    print('Native conversation check: ' + report['status'] + '. Report: ' + str(report_path), flush=True)
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    report = verify_native(args.root.expanduser().resolve(strict=True), startup_timeout=15)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
