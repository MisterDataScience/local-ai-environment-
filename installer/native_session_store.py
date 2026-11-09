"""Read committed OpenCode child evidence when its pinned history codec fails."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


VERSION = '1.18.34'
MAX_MESSAGES = 500
MAX_BYTES = 8 * 1024 * 1024


def read_child_messages(database, session_id, parent_id, call_id, agent, model_id,
                        task_status='running'):
    """Read native records only. This function never creates execution evidence."""
    path = Path(database).absolute()
    if not path.is_file() or path.is_symlink():
        raise ValueError('Native history database must be an existing regular file')
    if agent not in ('coder', 'coder-plan') or task_status not in ('running', 'completed'):
        raise ValueError('Invalid native coder execution profile')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only = ON')
        db.execute('BEGIN')
        parent = db.execute('SELECT id, parent_id, version FROM session WHERE id = ?', (parent_id,)).fetchone()
        child = db.execute('SELECT id, parent_id, agent, version FROM session WHERE id = ?', (session_id,)).fetchone()
        if (parent is None or parent['parent_id'] is not None or parent['version'] != VERSION or
                child is None or child['parent_id'] != parent_id or child['agent'] != agent or
                child['version'] != VERSION):
            raise ValueError('Native child identity does not match its coordinator and pinned version')
        matches = []
        for row in db.execute('SELECT id, data FROM part WHERE session_id = ?', (parent_id,)):
            part = json.loads(row['data'])
            if part.get('type') == 'tool' and part.get('tool') == 'task' and call_id in (row['id'], part.get('callID')):
                matches.append(part)
        if len(matches) != 1:
            raise ValueError('Native child has no unique coordinator task')
        state = matches[0].get('state', {})
        if (state.get('status') != task_status or state.get('metadata', {}).get('sessionId') != session_id or
                state.get('input', {}).get('subagent_type') != agent):
            raise ValueError('Native coordinator task does not match the child execution')
        rows = db.execute('SELECT id, data FROM message WHERE session_id = ? '
                          'ORDER BY time_created, id LIMIT ?', (session_id, MAX_MESSAGES + 1)).fetchall()
        if len(rows) > MAX_MESSAGES:
            raise ValueError('Native child message history exceeds the supported bound')
        messages, saw_format = [], False
        for row in rows:
            info = dict(json.loads(row['data']), id=row['id'], sessionID=session_id)
            if info.get('role') == 'user':
                model = info.get('model', {})
                if (info.get('agent') != agent or model.get('modelID') != model_id or
                        model.get('providerID') != 'local-ai-gateway'):
                    raise ValueError('Native child input uses an unexpected model or agent')
                saw_format |= info.get('format', {}).get('type') == 'json_schema'
            elif info.get('role') == 'assistant':
                if (info.get('agent') != agent or info.get('modelID') != model_id or
                        info.get('providerID') != 'local-ai-gateway'):
                    raise ValueError('Native child output uses an unexpected model or agent')
            else:
                raise ValueError('Unexpected native child message role')
            parts = []
            for part in db.execute('SELECT id, data FROM part WHERE session_id = ? AND message_id = ? '
                                   'ORDER BY id', (session_id, row['id'])):
                parts.append(dict(json.loads(part['data']), id=part['id'], messageID=row['id'], sessionID=session_id))
            messages.append({'info': info, 'parts': parts})
        if not saw_format:
            raise ValueError('Native child has no structured-format input to explain the API codec failure')
    result = {'source': 'native_sqlite_readonly', 'session_id': session_id,
              'parent_id': parent_id, 'messages': messages}
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError('Native child history exceeds the supported byte bound')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('database', 'session-id', 'parent-id', 'call-id', 'agent', 'model-id'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        result = read_child_messages(args.database, args.session_id, args.parent_id,
                                     args.call_id, args.agent, args.model_id)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        print('Native history read failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
