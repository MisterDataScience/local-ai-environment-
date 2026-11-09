"""Private diagnostics for fixed native acceptance fixtures, never ordinary chats."""
import datetime
import hashlib
import json
from pathlib import Path
import re

from feature_state import atomic_json


def diagnostic_path(root, check):
    name = check if re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', check) else (
        re.sub(r'[^A-Za-z0-9_.-]', '_', check)[:80] + '-' + hashlib.sha256(check.encode()).hexdigest()[:12])
    return Path(root) / 'logs/native-acceptance' / (name + '.json')


def capture(root, check, identifier, preset, request, *, prompt, residency=None):
    """Run one fixed smoke fixture; save its response before checking readiness."""
    from turnkey_install import ReadinessError
    path = diagnostic_path(root, check)
    record = {'version': 1, 'check': check, 'model_id': identifier,
              'tested_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'backend': preset.get('backend', 'ollama'), 'thinking': preset.get('thinking', True),
              'fixture_prompt': prompt, 'status': 'testing', 'stage': 'generation'}
    atomic_json(path, record)
    try:
        response = request()
    except Exception as error:
        record.update(status='failed', issue='generation_request_failed', error_type=type(error).__name__)
        atomic_json(path, record)
        raise ReadinessError(f'{check}: generation request failed ({type(error).__name__}); diagnostic: {path}') from error
    if not isinstance(response, dict):
        record.update(status='failed', issue='invalid_completion')
        atomic_json(path, record)
        raise ReadinessError(f'{check}: invalid completion response; diagnostic: {path}')
    # Only protocol data is retained. Never persist config, auth headers or keys.
    snapshot = {key: response[key] for key in ('model', 'choices', 'usage', 'timings') if key in response}
    if len(json.dumps(snapshot).encode()) > 1_000_000:
        record.update(status='failed', issue='acceptance_response_too_large', response_omitted=True)
        atomic_json(path, record)
        raise ReadinessError(f'{check}: acceptance response exceeds diagnostic limit; diagnostic: {path}')
    record.update(response=snapshot, stage='final_answer')
    atomic_json(path, record)
    try:
        choice = response['choices'][0]
        message = choice['message']
        content = message.get('content', '')
        reasoning = message.get('reasoning_content', '')
        finish = choice.get('finish_reason', 'stop')
        record.update(final_chars=len(content) if isinstance(content, str) else 0,
                      reasoning_chars=len(reasoning) if isinstance(reasoning, str) else 0,
                      finish_reason=finish)
        if finish == 'length':
            record['issue'] = 'output_cutoff'
            raise ReadinessError(f'{check}: generation was cut off before acceptance')
        if not isinstance(content, str) or not content.strip():
            record['issue'] = 'reasoning_without_final_answer' if record['reasoning_chars'] else 'empty_final_answer'
            raise ReadinessError(f'{check}: no final answer; reasoning characters={record["reasoning_chars"]}')
        if finish != 'stop':
            record['issue'] = 'unexpected_finish_reason'
            raise ReadinessError(f'{check}: response did not finish as a final answer')
        if residency is not None:
            record['stage'] = 'residency'
            atomic_json(path, record)
            record['residency'] = residency()
    except Exception as error:
        record.update(status='failed', error_type=type(error).__name__)
        record.setdefault('issue', 'residency_check_failed' if record['stage'] == 'residency' else 'invalid_completion')
        atomic_json(path, record)
        detail = str(error) if isinstance(error, ReadinessError) else f'{check}: {record["issue"]}'
        raise ReadinessError(f'{detail}; diagnostic: {path}') from error
    record.update(status='passed', stage='complete')
    atomic_json(path, record)
    return content, path
