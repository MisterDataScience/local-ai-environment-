"""Owner-authorized recurring inference using native per-user launchd jobs.

No scheduler daemon, shell command, autonomous permission grant or tool loop.
Interactive actions remain in the existing Work Agent approval workflow.
"""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile
import uuid

from common import http

PREFIX = 'local.local-ai.task.'


def atomic_json(path, value):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Unsafe task state')
    fd, temporary = tempfile.mkstemp(prefix='.task-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate(task):
    if not isinstance(task, dict) or set(task) != {'id', 'prompt', 'model', 'schedule', 'authorized'}:
        raise ValueError('Invalid scheduled task')
    if not re.fullmatch(r'[a-f0-9]{32}', task['id']) or task['authorized'] is not True:
        raise ValueError('Task has not been authorized')
    if not isinstance(task['prompt'], str) or not 1 <= len(task['prompt']) <= 8000 or not isinstance(task['model'], str):
        raise ValueError('Invalid task prompt or model')
    schedule = task['schedule']
    if not isinstance(schedule, dict):
        raise ValueError('Invalid schedule')
    if set(schedule) == {'interval'} and type(schedule['interval']) is int and 900 <= schedule['interval'] <= 604800:
        return
    if set(schedule) == {'hour', 'minute'} and type(schedule['hour']) is int and type(schedule['minute']) is int and 0 <= schedule['hour'] <= 23 and 0 <= schedule['minute'] <= 59:
        return
    raise ValueError('Use an interval of at least 15 minutes or a daily local time')


def launch_agent(root, task):
    validate(task)
    schedule = task['schedule']
    result = {'Label': PREFIX + task['id'], 'ProgramArguments': [str(root / 'control/.venv/bin/python'),
        str(root / 'control/scheduled_tasks.py'), '--root', str(root), '--run', task['id']],
        'WorkingDirectory': str(root / 'control'), 'ProcessType': 'Background',
        'StandardOutPath': str(root / 'logs/scheduled-tasks.log'),
        'StandardErrorPath': str(root / 'logs/scheduled-tasks-error.log')}
    if 'interval' in schedule:
        result['StartInterval'] = schedule['interval']
    else:
        result['StartCalendarInterval'] = {'Hour': schedule['hour'], 'Minute': schedule['minute']}
    return result


def slot(task, now):
    if 'interval' in task['schedule']:
        return str(int(now.timestamp()) // task['schedule']['interval'])
    return now.strftime('%Y-%m-%d')


def run_task(root, task_id, now=None):
    if not re.fullmatch(r'[a-f0-9]{32}', task_id):
        raise ValueError('Invalid task id')
    folder = root / 'control/scheduled-tasks'
    task_path = folder / (task_id + '.json')
    if task_path.is_symlink():
        raise ValueError('Unsafe task definition')
    task = json.loads(task_path.read_text())
    validate(task)
    if task['id'] != task_id:
        raise ValueError('Task identity mismatch')
    now = now or dt.datetime.now().astimezone()
    current_slot = slot(task, now)
    status_path = folder / (task_id + '.status.json')
    fd = os.open(folder / (task_id + '.lock'), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'already-running'}
        previous = json.loads(status_path.read_text()) if status_path.exists() else {}
        if previous.get('slot') == current_slot:
            return previous  # Includes unknown/failed results: never silently duplicate a job.
        record = {'task': task_id, 'slot': current_slot, 'time': now.isoformat(), 'status': 'running'}
        atomic_json(status_path, record)
        try:
            config = json.loads((root / 'control/config.json').read_text())
            mode = http('http://127.0.0.1:8001/control/mode', key=config['api_key'], timeout=5)
            if mode['mode'] == 'gaming' or mode['transitioning'] or mode['error']:
                raise RuntimeError('Resource policy blocked task')
            if config.get('vault', {}).get('enabled'):
                from vault_tools import mounted_root
                with mounted_root(config):
                    pass  # Do not infer or save plaintext while protected output is locked.
            result = http('http://127.0.0.1:8001/v1/chat/completions', {
                'model': task['model'], 'max_tokens': 2048, 'tool_choice': 'none', 'inference_only': True,
                'messages': [{'role': 'system', 'content': 'Run only the owner-authorized text task. You have no tools, network, current external data or file access. If tools, files, approvals or fresh information are required, return ACTION_REQUIRES_APPROVAL followed by what is needed. Do not claim actions were performed.'},
                             {'role': 'user', 'content': task['prompt']}]}, key=config['api_key'], timeout=1900)
            message = result['choices'][0]['message']
            answer = message.get('content')
            if message.get('tool_calls') or not isinstance(answer, str) or not answer.strip():
                raise RuntimeError('Scheduled result requires interactive handling')
            name = task_id + '-' + current_slot + '.md'
            if config.get('vault', {}).get('enabled'):
                from vault_tools import execute
                saved = execute(config, 'workspace_write', {'path': 'Outputs/' + name,
                    'content': answer, 'expected_sha256': ''})['saved']
            else:
                output = root / 'work-agent/scheduled-outputs'
                output.mkdir(parents=True, mode=0o700, exist_ok=True)
                if output.is_symlink():
                    raise ValueError('Unsafe task output directory')
                saved = str(output / name)
                fd = os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'w') as out:
                    out.write(answer)
            finish = result['choices'][0].get('finish_reason')
            status = ('incomplete' if finish == 'length' else
                      'needs-approval' if 'ACTION_REQUIRES_APPROVAL' in answer else 'completed')
            record.update(status=status, output=saved, finish_reason=finish)
        except Exception:
            # No exception body, prompt or answer leaks into unencrypted logs.
            record.update(status='blocked-or-failed', notice='Check gateway readiness, resource mode, vault mount and task requirements. No automatic retry in this slot.')
        atomic_json(status_path, record)
        return record


def configure(root):
    config = json.loads((root / 'control/config.json').read_text())
    print('Scheduled tasks run text inference only. Tools, browsing and file operations require interactive approval. Definitions are local plaintext; outputs use the vault when configured.')
    prompt = input('Exact recurring task: ').strip()
    model = input('Configured model ID [local-ai]: ').strip() or 'local-ai'
    if model not in config['text_models']:
        raise ValueError('Unknown model')
    timing = input('Daily HH:MM local time, or interval minutes: ').strip()
    if ':' in timing:
        hour, minute = map(int, timing.split(':'))
        schedule = {'hour': hour, 'minute': minute}
    else:
        schedule = {'interval': int(timing) * 60}
    task = {'id': uuid.uuid4().hex, 'prompt': prompt, 'model': model, 'schedule': schedule, 'authorized': True}
    validate(task)
    print(json.dumps(task, indent=2))
    if input('Type AUTHORIZE to register this exact recurring task: ').strip() != 'AUTHORIZE':
        raise RuntimeError('Task was not authorized; nothing registered')
    folder = root / 'control/scheduled-tasks'
    atomic_json(folder / (task['id'] + '.json'), task)
    agents = Path.home() / 'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = agents / (PREFIX + task['id'] + '.plist')
    with path.open('xb') as out:
        out.write(plistlib.dumps(launch_agent(root, task)))
    path.chmod(0o600)
    try:
        subprocess.run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)], check=True)
    except Exception:
        path.unlink(missing_ok=True)
        (folder / (task['id'] + '.json')).unlink(missing_ok=True)
        raise
    atomic_json(folder / (task['id'] + '.status.json'), {'task': task['id'], 'status': 'scheduled-not-yet-run', 'slot': None})
    print('Task registered:', task['id'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--configure', action='store_true')
    actions.add_argument('--status', action='store_true')
    actions.add_argument('--remove', action='store_true')
    actions.add_argument('--run')
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.configure:
        configure(root)
    elif args.run:
        print(json.dumps(run_task(root, args.run)))
    elif args.status:
        for path in sorted((root / 'control/scheduled-tasks').glob('*.status.json')):
            if not path.is_symlink():
                print(path.read_text())
    else:
        task_id = input('Task ID to remove: ').strip()
        if not re.fullmatch(r'[a-f0-9]{32}', task_id):
            raise ValueError('Invalid task ID')
        path = Path.home() / 'Library/LaunchAgents' / (PREFIX + task_id + '.plist')
        subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}/{PREFIX}{task_id}'], capture_output=True)
        if path.is_symlink():
            raise ValueError('Unsafe LaunchAgent')
        path.unlink(missing_ok=True)
        (root / 'control/scheduled-tasks' / (task_id + '.json')).unlink(missing_ok=True)
        print('Recurring task removed; existing results retained.')


if __name__ == '__main__':
    main()
