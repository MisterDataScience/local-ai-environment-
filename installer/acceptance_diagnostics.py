"""Collect a complete saved Captain failure, or retry only that native stage."""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time


TITLE = 'Native captain acceptance'
MAX_MESSAGES = 500
MAX_BYTES = 16 * 1024 * 1024


def _secret_key(key):
    key = str(key).lower().replace('-', '_')
    return any(word in key for word in ('password', 'secret', 'api_key', 'private_key', 'authorization')) or key in ('token', 'access_token', 'refresh_token')


def _secrets(value):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _secret_key(key) and isinstance(item, str) and item:
                found.append(item)
            found.extend(_secrets(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_secrets(item))
    return sorted(set(found), key=len, reverse=True)


def _redact(value, secrets):
    if isinstance(value, dict):
        return {key: '[redacted]' if _secret_key(key) else _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, '[redacted]')
        return re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [redacted]', value)
    return value


def _session(db, row):
    rows = db.execute('SELECT id, data FROM message WHERE session_id=? ORDER BY time_created,id LIMIT ?',
                      (row['id'], MAX_MESSAGES + 1)).fetchall()
    if len(rows) > MAX_MESSAGES:
        raise ValueError('Acceptance session exceeds the 500-message diagnostic bound')
    messages = []
    for message in rows:
        info = dict(json.loads(message['data']), id=message['id'], sessionID=row['id'])
        parts = []
        for part in db.execute('SELECT id,data FROM part WHERE session_id=? AND message_id=? ORDER BY id',
                               (row['id'], message['id'])):
            data = dict(json.loads(part['data']), id=part['id'], messageID=message['id'], sessionID=row['id'])
            if data.get('type') == 'reasoning':
                data = {'type': 'reasoning', 'chars': len(data.get('text', '')), 'id': part['id']}
            parts.append(data)
        messages.append({'info': info, 'parts': parts})
    return {**dict(row), 'messages': messages}


def collect(root, *, session_id=None, since_ms=None, reason=None):
    """Read only the reserved Captain acceptance session and its own reports."""
    root = Path(root).expanduser().absolute()
    report = {'diagnostic_kind': 'local_ai_acceptance', 'version': 1, 'stage': 'captain',
        'captured_at': datetime.now(timezone.utc).isoformat(), 'action': 'inspect_saved_state',
        'new_inference_requested': False, 'full_installation_acceptance_performed': False,
        'sessions': [], 'captain_turns': {}, 'worker_reports': [], 'logs': [], 'collection_errors': []}
    config = {}
    try:
        config = json.loads((root / 'control/config.json').read_text())
        if not isinstance(config, dict):
            raise ValueError('Saved configuration is not an object')
    except (OSError, ValueError) as error:
        config = {}
        report['collection_errors'].append('Configuration: ' + str(error))
    secrets = _secrets(config)
    report['configuration'] = {
        'captain': {key: config.get('captain', {}).get(key) for key in
                    ('enabled', 'provider', 'model_id', 'single_model', 'max_parallel')},
        'text_models': {name: {key: value.get(key) for key in ('backend', 'model', 'num_ctx', 'thinking')}
                        for name, value in config.get('text_models', {}).items() if isinstance(value, dict)}}
    report['installed_source_sha256'] = {}
    for name in ('captain.mjs', 'captain-runtime.mjs', 'captain_check.py', 'opencode-team.mjs',
                 'work_agent.py', 'shared_llama.py', 'native_session_store.py'):
        path = root / 'control' / name
        if path.is_file():
            report['installed_source_sha256'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    parent = None
    databases = root / 'work-agent/state/data/opencode'
    for path in sorted(databases.glob('opencode*.db'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
                db.row_factory = sqlite3.Row
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                query = 'SELECT id,parent_id,title,time_created FROM session WHERE parent_id IS NULL AND title=?'
                parameters = [TITLE]
                if session_id is not None:
                    query += ' AND id=?'
                    parameters.append(session_id)
                if since_ms is not None:
                    query += ' AND time_created>=?'
                    parameters.append(since_ms)
                row = db.execute(query + ' ORDER BY time_created DESC LIMIT 1', parameters).fetchone()
                if row is None or parent is not None and row['time_created'] <= parent['time_created']:
                    continue
                children = db.execute('SELECT id,parent_id,title,time_created FROM session WHERE parent_id=? '
                                      'ORDER BY time_created,id LIMIT 25', (row['id'],)).fetchall()
                if len(children) > 24:
                    raise ValueError('Acceptance has more than 24 child sessions')
                sessions = [_session(db, row), *[_session(db, child) for child in children]]
                parent, report['sessions'], report['database'] = dict(row), sessions, str(path)
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
            report['collection_errors'].append(str(path) + ': ' + str(error))
    if parent:
        report['session_id'] = parent['id']
        user_ids = [message['info']['id'] for message in report['sessions'][0]['messages']
                    if message['info'].get('role') == 'user']
        keys = {hashlib.sha256((parent['id'] + '\0' + user_id).encode()).hexdigest() for user_id in user_ids}
        ledger = root / 'work-agent/state/captain.json'
        try:
            turns = json.loads(ledger.read_text()).get('turns', {})
            report['captain_turns'] = {key: turns[key] for key in keys if key in turns}
        except (OSError, ValueError, AttributeError) as error:
            report['collection_errors'].append('Captain ledger: ' + str(error))
        paths = set()
        for turn in report['captain_turns'].values():
            paths.update(task['report'] for task in turn.get('tasks', []) if task.get('report'))
        for message in report['sessions'][0]['messages']:
            for part in message['parts']:
                if part.get('type') == 'tool' and part.get('tool') == 'team_run':
                    try:
                        value = json.loads(part.get('state', {}).get('output', '{}'))
                        paths.update(task['report'] for task in value.get('tasks', []) if task.get('report'))
                    except (ValueError, TypeError, AttributeError):
                        pass
        allowed = (root / 'work-agent/captain-acceptance/.local-ai-team').resolve()
        for name in sorted(paths):
            path = Path(name)
            if path.is_symlink() or path.resolve().parent != allowed:
                report['collection_errors'].append('Worker report is outside the acceptance report directory')
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError('Worker report exceeds 2 MiB')
                report['worker_reports'].append({'path': str(path), 'report': json.loads(path.read_text())})
            except (OSError, ValueError) as error:
                report['collection_errors'].append('Worker report: ' + str(error))
        native_log = root / 'work-agent/state/data/opencode/log/opencode.log'
        try:
            if native_log.is_file():
                with native_log.open('rb') as stream:
                    size = native_log.stat().st_size
                    stream.seek(max(0, size - 512 * 1024))
                    lines = stream.read().decode('utf-8', errors='replace').splitlines()
                run = next((re.search(r'\brun=([^ ]+)', line) for line in reversed(lines)
                            if parent['id'] in line and re.search(r'\brun=([^ ]+)', line)), None)
                identifiers = {session['id'] for session in report['sessions']}
                selected = [line for line in lines if ('run=' + run.group(1) + ' ' in line if run
                            else any(identifier in line for identifier in identifiers))]
                report['logs'].append({'path': str(native_log), 'tail_bytes': 512 * 1024,
                                       'earlier_bytes_omitted': max(0, size - 512 * 1024), 'lines': selected})
        except OSError as error:
            report['collection_errors'].append('Native log: ' + str(error))
    progress = root / 'acceptance-report.json'
    if progress.is_file():
        try:
            saved = json.loads(progress.read_text())
            report['recorded_core_checks'] = [{key: row.get(key) for key in ('name', 'status', 'model_id', 'seconds')}
                                              for row in saved.get('checks', []) if isinstance(row, dict)]
        except (OSError, ValueError, AttributeError) as error:
            report['collection_errors'].append('Core progress: ' + str(error))
    core_receipt = root / 'state/features/core.json'
    if core_receipt.is_file():
        try:
            row = json.loads(core_receipt.read_text())
            report['core_feature_state'] = {key: row.get(key) for key in
                                           ('status', 'current_stage', 'last_failure', 'next_action')}
        except (OSError, ValueError, AttributeError) as error:
            report['collection_errors'].append('Core feature state: ' + str(error))
    if reason:
        report['check_failure'] = str(reason)
    report['summary'] = summarize(report)
    report = _redact(report, secrets)
    if len(json.dumps(report, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError('Diagnostic exceeds 16 MiB; nothing was silently truncated')
    return report


def summarize(report):
    errors, tools, parent_tools = [], {}, {}
    for session in report['sessions']:
        for message in session['messages']:
            info = message['info']
            if info.get('error'):
                errors.append({'session_id': session['id'], 'message_id': info['id'], 'error': info['error']})
            for part in message['parts']:
                if part.get('type') != 'tool':
                    continue
                state, tool = part.get('state', {}), part.get('tool', 'unknown')
                counts = tools.setdefault(tool, {})
                status = state.get('status', 'unknown')
                counts[status] = counts.get(status, 0) + 1
                if session['id'] == report.get('session_id'):
                    parent_counts = parent_tools.setdefault(tool, {})
                    parent_counts[status] = parent_counts.get(status, 0) + 1
                if state.get('error'):
                    errors.append({'session_id': session['id'], 'tool': tool,
                                   'call_id': part.get('callID'), 'error': state['error']})
    workers = [task for turn in report['captain_turns'].values() for task in turn.get('tasks', [])]
    for task in workers:
        if task.get('error'):
            errors.append({'worker_id': task.get('id'), 'error': task['error']})
    final = ''
    if report['sessions']:
        last = next((message for message in reversed(report['sessions'][0]['messages'])
                     if message['info'].get('role') == 'assistant'), None)
        if last:
            final = '\n'.join(part.get('text', '') for part in last['parts'] if part.get('type') == 'text')
    return {'status': 'saved_captain_session_found' if report['sessions'] else 'no_matching_captain_session',
        'session_id': report.get('session_id'), 'tools': tools, 'parent_tools': parent_tools, 'errors': errors,
        'workers': [{key: task.get(key) for key in ('id', 'role', 'status', 'retired', 'error')} for task in workers],
        'final_reply': final[:1600], 'final_reply_truncated': len(final) > 1600,
        'collection_errors': report['collection_errors']}


def save(path, report):
    path = Path(path).expanduser().absolute()
    if path.is_symlink():
        raise ValueError('Diagnostic output must not be a symbolic link')
    if path.exists():
        old = json.loads(path.read_text())
        if not isinstance(old, dict) or old.get('diagnostic_kind') != 'local_ai_acceptance':
            raise ValueError('Existing output is not a Local AI diagnostic; choose another --output')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic_bytes(path, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
    return path


def _atomic_bytes(path, content):
    fd, temporary = tempfile.mkstemp(prefix='.local-ai-diagnostic-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _captain_acceptance_stage(root):
    """Hold the core testing state until owned services stop, then restore it."""
    config = json.loads((root / 'control/config.json').read_text())
    if config.get('feature_schema') != 1:
        yield
        return
    from feature_state import state_path, read, write, safe_path
    path = state_path(root, 'core')
    read(root, 'core')  # Validate an existing receipt before changing it.
    original = path.read_bytes() if path.exists() else None
    write(root, 'core', 'testing', current_stage='captain-scoped-acceptance')
    staged = path.read_bytes()
    try:
        yield
    finally:
        # Do not overwrite a concurrent manual change or follow a replaced link.
        safe_path(path)
        if not path.is_file() or path.read_bytes() != staged:
            raise RuntimeError('Core receipt changed during scoped acceptance; preserving it')
        if original is None:
            path.unlink()
        else:
            _atomic_bytes(path, original)


def retry_captain(root):
    """Use existing installed services and native acceptance; never install software."""
    root = Path(root).expanduser().absolute()
    sys.path.insert(0, str(root / 'control'))
    from feature_state import installation_lock
    from feature_install import ensure_stopped
    from feature_checks import services
    from captain_check import verify
    started = int(time.time() * 1000)
    failure, checks, cleanup_errors = None, [], []
    phase, failed_phase, inference_requested = 'preflight', None, False
    try:
        with installation_lock(root):
            ensure_stopped(root)
            phase = 'acceptance_state_setup'
            with _captain_acceptance_stage(root):
                phase = 'services_startup'
                with services(root, ('core',)) as config:
                    phase, inference_requested = 'captain_native_check', True
                    try:
                        checks = verify(root, config)
                        if not checks or not any(row.get('name') == 'native-captain-team' and
                                                row.get('status') == 'passed' for row in checks):
                            raise RuntimeError('Captain check did not return a native pass')
                    except Exception as error:
                        failure, failed_phase = str(error), phase
                    phase = 'services_cleanup'
                phase = 'acceptance_state_restore'
    except Exception as error:
        if failure is None:
            failure, failed_phase = str(error), phase
        else:
            cleanup_errors.append(str(error))
    report = collect(root, since_ms=started, reason=failure)
    report.update(action='retry_captain', new_inference_requested=inference_requested,
                  probe={'stage': 'captain', 'status': 'failed' if failure or cleanup_errors else 'passed',
                         'failure_stage': failed_phase, 'checks': checks, 'error': failure,
                         'cleanup_errors': cleanup_errors})
    # No accepted-core fingerprint is written. The prior feature receipt is
    # restored after the temporary installer-owned testing state is released.
    try:
        secrets = _secrets(json.loads((root / 'control/config.json').read_text()))
    except (OSError, ValueError):
        secrets = []
    return _redact(report, secrets)


def console_summary(report, path):
    saved = report['summary']
    errors = saved['errors']
    first = dict(errors[0]) if errors else None
    if first is not None:
        value = first['error']
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        first['error'], first['error_truncated'] = text[:1400], len(text) > 1400
    result = {'diagnostic': str(path), 'status': saved['status'], 'session_id': saved['session_id'],
              'parent_tools': saved['parent_tools'], 'error_count': len(errors), 'first_error': first,
              'workers': saved['workers'], 'final_reply': saved['final_reply'][:600],
              'collection_errors': saved['collection_errors']}
    if 'probe' in report:
        result['probe'] = report['probe']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'LocalAI-Automated')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--retry', choices=('captain',))
    args = parser.parse_args()
    root = args.root.expanduser().absolute()
    target = args.output or root / 'logs/native-acceptance/captain-diagnostic.json'
    report = retry_captain(root) if args.retry else collect(root)
    path = save(target, report)
    summary = console_summary(report, path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if report.get('probe', {}).get('status') == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
