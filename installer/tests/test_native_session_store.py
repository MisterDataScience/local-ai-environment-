"""Real SQLite identity and evidence checks for the pinned history-codec repair."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_session_store import read_child_messages


def create_history(database, *, read_status='running', final=False, final_text='',
                   claimed_id='read-real', task_status='running', native_format=None,
                   parent_id='session1', call_id='delegate', model_id='code', test_claim=False):
    path = Path(database)
    if path.exists():
        path.unlink()
    result = {'summary': '17 times 20 is 340; subtracting 17 gives 323.',
        'acceptance': [{'id': 'A1', 'status': 'met', 'evidence': 'Inspected the supplied arithmetic.',
                        'tool_call_ids': [claimed_id]}],
        'changed_files': [], 'tests': [], 'assumptions': [], 'unresolved': []}
    if test_claim:
        result['tests'] = [{'tool_call_id': 'never-run', 'command': 'npm test', 'status': 'passed'}]
    if final_text == 'same-json':
        final_text = json.dumps(result, indent=2) + '\n\n'
    elif final_text == 'conflicting-json':
        final_text = json.dumps(dict(result, summary='Conflicting final text'))
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE session(id TEXT PRIMARY KEY,parent_id TEXT,agent TEXT,version TEXT);'
            'CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,time_created INTEGER,data TEXT);'
            'CREATE TABLE part(id TEXT PRIMARY KEY,session_id TEXT,message_id TEXT,data TEXT);')
        db.executemany('INSERT INTO session VALUES(?,?,?,?)', [
            (parent_id, None, 'plan', '1.18.34'), ('child', parent_id, 'coder-plan', '1.18.34'),
            ('private', None, 'build', '1.18.34')])
        task = {'type': 'tool', 'tool': 'task', 'callID': call_id, 'state': {
            'status': task_status, 'input': {'subagent_type': 'coder-plan'}, 'metadata': {'sessionId': 'child'}}}
        db.execute('INSERT INTO part VALUES(?,?,?,?)', ('parent-task', parent_id, 'parent-assistant', json.dumps(task)))
        user = {'role': 'user', 'agent': 'coder-plan', 'model': {'providerID': 'local-ai-gateway', 'modelID': model_id},
                'format': native_format or {'type': 'json_schema', 'schema': {'type': 'object'}, 'retryCount': 0}}
        assistant = {'role': 'assistant', 'agent': 'coder-plan', 'modelID': model_id,
                     'providerID': 'local-ai-gateway', 'parentID': 'child-user', 'finish': 'tool-calls'}
        db.executemany('INSERT INTO message VALUES(?,?,?,?)', [
            ('child-user', 'child', 1, json.dumps(user)), ('read-message', 'child', 2, json.dumps(assistant)),
            ('private-message', 'private', 3, json.dumps({'role': 'assistant', 'secret': 'UNRELATED_PRIVATE_TEXT'}))])
        state = {'status': read_status, 'input': {'filePath': 'coder-acceptance.txt'}}
        if read_status == 'error':
            state['error'] = 'Native inspection failed'
        elif read_status == 'completed':
            state.update(output='17 * 20 - 17 = 323.', metadata={})
        db.execute('INSERT INTO part VALUES(?,?,?,?)', ('read-part', 'child', 'read-message',
            json.dumps({'type': 'tool', 'tool': 'read', 'callID': 'read-real', 'state': state})))
        if final:
            db.execute('INSERT INTO message VALUES(?,?,?,?)', ('final-message', 'child', 3,
                json.dumps(dict(assistant, structured=result))))
            db.execute('INSERT INTO part VALUES(?,?,?,?)', ('format-part', 'child', 'final-message', json.dumps({
                'type': 'tool', 'tool': 'StructuredOutput', 'callID': 'format-real',
                'state': {'status': 'completed', 'input': result, 'output': 'Structured output captured successfully.'}})))
            if final_text:
                db.execute('INSERT INTO part VALUES(?,?,?,?)', ('text-part', 'child', 'final-message',
                    json.dumps({'type': 'text', 'text': final_text})))


class NativeSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / 'opencode.db'
        create_history(self.database)

    def read(self, **options):
        return read_child_messages(self.database, 'child', 'session1', 'delegate', 'coder-plan', 'code', **options)

    def test_reads_real_records_without_changing_database_or_exposing_other_sessions(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        result = self.read()
        self.assertEqual(result['source'], 'native_sqlite_readonly')
        self.assertEqual(result['messages'][1]['parts'][0]['callID'], 'read-real')
        self.assertEqual(result['messages'][1]['parts'][0]['state']['status'], 'running')
        self.assertNotIn('UNRELATED_PRIVATE_TEXT', json.dumps(result))
        self.assertEqual(before, hashlib.sha256(self.database.read_bytes()).hexdigest())

    def test_failed_inspection_is_preserved_and_cannot_become_completed_evidence(self):
        create_history(self.database, read_status='error', final=True)
        result = self.read()
        self.assertEqual(result['messages'][1]['parts'][0]['state'], {
            'status': 'error', 'input': {'filePath': 'coder-acceptance.txt'}, 'error': 'Native inspection failed'})
        self.assertEqual(result['messages'][-1]['info']['structured']['acceptance'][0]['tool_call_ids'], ['read-real'])

    def test_completed_acceptance_reads_require_the_completed_native_task(self):
        with self.assertRaisesRegex(ValueError, 'coordinator task'):
            self.read(task_status='completed')
        create_history(self.database, task_status='completed', read_status='completed', final=True)
        self.assertEqual(len(self.read(task_status='completed')['messages']), 3)

    def test_parent_profile_version_input_and_model_mismatches_are_rejected(self):
        mutations = [
            ('UPDATE session SET parent_id=? WHERE id=?', ('private', 'child')),
            ('UPDATE session SET version=? WHERE id=?', ('different-version', 'child')),
            ('UPDATE session SET agent=? WHERE id=?', ('analyst', 'child')),
        ]
        for sql, args in mutations:
            create_history(self.database)
            with sqlite3.connect(self.database) as db:
                db.execute(sql, args)
            with self.assertRaises(ValueError):
                self.read()
        for field, value in [('modelID', 'other'), ('providerID', 'other')]:
            create_history(self.database)
            with sqlite3.connect(self.database) as db:
                info = json.loads(db.execute('SELECT data FROM message WHERE id=?', ('read-message',)).fetchone()[0])
                info[field] = value
                db.execute('UPDATE message SET data=? WHERE id=?', (json.dumps(info), 'read-message'))
            with self.assertRaisesRegex(ValueError, 'unexpected model'):
                self.read()

    def test_wrong_task_and_missing_or_unstructured_database_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unique coordinator task'):
            read_child_messages(self.database, 'child', 'session1', 'invented-task', 'coder-plan', 'code')
        with sqlite3.connect(self.database) as db:
            info = json.loads(db.execute('SELECT data FROM message WHERE id=?', ('child-user',)).fetchone()[0])
            info.pop('format')
            db.execute('UPDATE message SET data=? WHERE id=?', (json.dumps(info), 'child-user'))
        with self.assertRaisesRegex(ValueError, 'structured-format input'):
            self.read()
        self.database.unlink()
        with self.assertRaisesRegex(ValueError, 'existing regular file'):
            self.read()
        self.assertFalse(self.database.exists())


if __name__ == '__main__':
    unittest.main()
