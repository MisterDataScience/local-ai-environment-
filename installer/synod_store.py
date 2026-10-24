"""The Synod's private, append-only dossiers and declarative studio packages.

The Village database is the archive of record and is included in Village backups.
Records are operational history, not publication into residents' approved memory.
"""
import json
import re
import time

import village
import village_memory as memory
from studio_store import ident, sha, encoded, bounded

SYNOD_ID = 'institution:' + sha('the-synod')[:32]
SYNOD_STUDIO = 'synod-studio:' + sha('the-synod')[:32]
PURPOSE = 'Create and repair studios, verify their operation, and preserve their institutional history.'
DEPARTMENTS = (
    ('purpose', 'Purpose and Scope', 'analyst'),
    ('workflow', 'Workflow Design', 'analyst'),
    ('institution', 'Institution Design', 'analyst'),
    ('construction', 'Construction', 'coder'),
    ('trials', 'Trials and Review', 'reviewer'),
)
CATEGORIES = ('commission', 'design', 'decision', 'construction', 'trial', 'specification', 'repair', 'pattern', 'failure')
STATES = ('proposed', 'approved', 'implemented', 'verified', 'rejected', 'blocked', 'observed')
STYLE = 'Use British English. Be direct. No flattery, reassurance, em dashes or invented evidence.'
CONSTRUCTION_CONTRACT = '''# Studio construction contract

Derived from docs/INSTITUTIONS-AND-STUDIOS.md and docs/STUDIO-IMPLEMENTATION-CHECKLIST.md.
These are the repository's installed architectural rules, not a substitute for a missing owner source.

Design the workflow before staffing it. Specify purpose, inputs, concrete outputs, acceptance checks,
failure states and revision routes. The Studio Lead owns the whole institution, reviews each saved
department handover and performs final closure. Specialists have independent contexts and scoped roles.
Do not bypass an existing studio's saved production controller or its single-game lane.

Prepare tests and acceptance criteria before implementation. Preserve immutable originals, provenance,
working drafts and versioned outputs separately. Independent review needs actual output and execution
evidence. Keep Observed, Inferred and Unverified distinct. A source map, model report or successful
compilation is not proof of correct behaviour or appearance. Missing visual/native acceptance stays open.

Role names are permission profiles, not capabilities. Reuse installed tools only through implemented
adapters. Never invent a shell, network or outsourcing capability. Local inference has finite budgets,
shared scheduling, cancellation and explicit pause/resume. Failed work remains recoverable.

Keep the institution's private Library and operational Archive separate from general Village knowledge.
Resident maps point to approved instructions and sources; large material is read in bounded pages.
Ordinary handovers and operational records are drafts/evidence, not approved personal memories.
Owner review is the final step for permanent staff, scope and published knowledge changes.

The Synod itself is built in without founding. Each creation explicitly chooses whether founding is
required. Preserve commissions, decisions with reasons and rejected alternatives, assumptions,
implementation locations/dependencies, trial evidence, current specification and repair history.
Use stable studio identities. Never overwrite historical specifications. Proposed, approved,
implemented and verified are distinct states. The Synod Lead is accountable for archive completeness.
Trial the actual commission route and a user reply before closing. Return faults for specific repair;
do not authorise unrelated institutional changes. Reusable patterns retain their supporting evidence.
'''
SPEC_SCHEMA = {
    'name': 'studio name', 'purpose': 'concrete deliverable and scope',
    'founding_required': False, 'founding_reason': 'why founding is or is not needed',
    'lead_instruction': 'lead responsibility and final acceptance rules',
    'capabilities': ['text'],
    'departments': [{'id': 'slug', 'title': 'department name', 'role': 'analyst|writer|reviewer|coder|researcher',
                     'instruction': 'work and limitations', 'inputs': 'required handover',
                     'output': 'concrete deliverable', 'acceptance': 'observable acceptance criteria'}],
    'trial': {'input': 'representative commission', 'acceptance': 'what the output must demonstrate'},
}


def validate_spec(spec):
    if not isinstance(spec, dict) or set(spec) != set(SPEC_SCHEMA):
        raise ValueError('Studio specification must match the supplied schema')
    out = {key: bounded(spec[key], limit, key, empty=False) for key, limit in
           [('name', 100), ('purpose', 1200), ('founding_reason', 600), ('lead_instruction', 1200)]}
    if type(spec['founding_required']) is not bool:
        raise ValueError('founding_required must be a boolean')
    out['founding_required'] = spec['founding_required']
    capabilities = spec['capabilities']
    if not isinstance(capabilities, list) or not 1 <= len(capabilities) <= 12:
        raise ValueError('Specify one to twelve required capabilities')
    out['capabilities'] = sorted(set(bounded(c, 80, 'capability', empty=False) for c in capabilities))
    departments = spec['departments']
    if not isinstance(departments, list) or not 1 <= len(departments) <= 8:
        raise ValueError('Specify one to eight departments')
    out['departments'] = []; seen = set()
    for dept in departments:
        if not isinstance(dept, dict) or set(dept) != set(SPEC_SCHEMA['departments'][0]):
            raise ValueError('Department must specify identity, role, instructions, inputs, output and acceptance')
        key = dept['id']
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,23}', key) or key in seen or key == 'lead':
            raise ValueError('Department IDs must be unique slugs, distinct from lead')
        seen.add(key)
        if dept['role'] not in village.ROLES:
            raise ValueError('Unknown department permission profile')
        out['departments'].append(dict(id=key, role=dept['role'], **{
            k: bounded(dept[k], 1200 if k == 'instruction' else 600, k, empty=False)
            for k in ('title', 'instruction', 'inputs', 'output', 'acceptance')}))
    trial = spec['trial']
    if not isinstance(trial, dict) or set(trial) != {'input', 'acceptance'}:
        raise ValueError('A representative trial input and acceptance criteria are required')
    out['trial'] = {k: bounded(trial[k], 1200, k, empty=False) for k in trial}
    if len(encoded(out).encode()) > 8000:
        raise ValueError('Studio specification exceeds its 8000-byte context bound')
    return out


class Archive:
    def __init__(self, store):
        self.store = store
        with store.db() as cx, cx:
            cx.executescript('''
                CREATE TABLE IF NOT EXISTS synod_schema(version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO synod_schema VALUES(1);
                CREATE TABLE IF NOT EXISTS synod_dossiers(
                    id TEXT PRIMARY KEY, institution TEXT UNIQUE, name TEXT NOT NULL,
                    current_spec TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS synod_commissions(
                    id TEXT PRIMARY KEY, studio TEXT NOT NULL REFERENCES synod_dossiers(id),
                    kind TEXT NOT NULL, brief TEXT NOT NULL, message TEXT NOT NULL,
                    state TEXT NOT NULL, phase TEXT NOT NULL, revision INTEGER NOT NULL,
                    pending TEXT NOT NULL DEFAULT '', approved TEXT NOT NULL DEFAULT '',
                    trial_message TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL, updated INTEGER NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS synod_one_commission ON synod_commissions(studio)
                    WHERE state NOT IN ('complete','cancelled');
                CREATE TABLE IF NOT EXISTS synod_records(
                    id TEXT PRIMARY KEY, studio TEXT NOT NULL REFERENCES synod_dossiers(id),
                    commission TEXT NOT NULL, sequence INTEGER NOT NULL, category TEXT NOT NULL,
                    state TEXT NOT NULL, actor TEXT NOT NULL, body TEXT NOT NULL, evidence TEXT NOT NULL,
                    previous TEXT NOT NULL, digest TEXT NOT NULL, event_key TEXT UNIQUE, created INTEGER NOT NULL,
                    UNIQUE(studio,sequence));
                CREATE INDEX IF NOT EXISTS synod_records_lookup ON synod_records(studio,category,sequence);
                CREATE TRIGGER IF NOT EXISTS synod_records_immutable_update BEFORE UPDATE ON synod_records
                    BEGIN SELECT RAISE(ABORT,'Synod archive records are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS synod_records_immutable_delete BEFORE DELETE ON synod_records
                    BEGIN SELECT RAISE(ABORT,'Synod archive records are append-only'); END;
                CREATE TABLE IF NOT EXISTS synod_packages(
                    institution TEXT PRIMARY KEY, studio TEXT NOT NULL REFERENCES synod_dossiers(id),
                    specification TEXT NOT NULL REFERENCES synod_records(id), state TEXT NOT NULL);
            ''')
            if [r[0] for r in cx.execute('SELECT version FROM synod_schema')] != [1]:
                raise RuntimeError('Unsupported Synod schema')
            now = int(time.time()); scope = 'institution.' + SYNOD_ID.split(':')[1]
            cx.execute('INSERT OR IGNORE INTO institutions VALUES(?,?,?,?,?,?,?,?)',
                       (SYNOD_ID, 'The Synod', 'studio', PURPOSE, scope, encoded(dict(work_bytes=64*1024*1024)), 'active', now))
            cx.execute('INSERT OR IGNORE INTO collections VALUES(?,?)', (scope, 'Private Synod archive'))
            cx.execute('INSERT OR IGNORE INTO synod_dossiers(id,institution,name,created) VALUES(?,?,?,?)',
                       (SYNOD_STUDIO, SYNOD_ID, 'The Synod', now))
            staff = [('lead', 'Studio Lead', 'analyst', 'Own every Synod commission and archive completeness. Review each handover; never self-approve a design.')]
            staff += [(key, title, role, 'Own the ' + title + ' handover. Preserve decisions, evidence and uncertainty.') for key, title, role in DEPARTMENTS]
            for key, title, role, instruction in staff:
                self.staff(cx, SYNOD_ID, 'studio.synod.' + key, title, role, instruction, 'built-in Synod')
            self.publish(cx, SYNOD_ID, CONSTRUCTION_CONTRACT, 'Studio construction contract', 'built-in Synod')
            if not cx.execute('SELECT 1 FROM synod_records WHERE studio=?', (SYNOD_STUDIO,)).fetchone():
                record = self.append(cx, SYNOD_STUDIO, '', 'specification', 'implemented', 'host', dict(
                    name='The Synod', purpose=PURPOSE, founding_required=False,
                    departments=[title for _, title, _ in DEPARTMENTS],
                    lead='Studio Lead', archive_accountability='Synod Lead',
                    runtime='Local bounded studio jobs; explicit approval before construction.',
                    capabilities=['text'], limitations='External tools and founding adapters require explicit implementation and trials.'), [], 'synod-bootstrap')
                cx.execute('UPDATE synod_dossiers SET current_spec=? WHERE id=?', (record, SYNOD_STUDIO))

    def publish(self, cx, iid, text, title, approval):
        """Install approved design navigation, never promote ordinary work into memory."""
        scope = 'institution.' + iid.split(':')[1]; now = int(time.time())
        citation = 'doc:' + sha(iid + text)[:32]
        cx.execute('INSERT OR IGNORE INTO library_documents VALUES(?,?,?,?,?,?,?,?,?)',
                   (citation, title, text, scope, '[]', sha(text), 'approved', now, approval))
        spec = dict(fast_access=[], glossary=[], preferred_sources=[dict(target=citation, label='Studio operating contract', when='Before studio work or a handover review')])
        for row in cx.execute('SELECT resident FROM institution_members WHERE institution=?', (iid,)).fetchall():
            sid = row[0]
            old = cx.execute('SELECT approval,body FROM resident_starting_maps WHERE specialist_id=?', (sid,)).fetchone()
            if old and not old['approval'].startswith(('built-in Synod', 'Owner Synod design approval ')): continue
            preview = memory.preview_map(cx, sid, spec)
            if old and json.loads(old['body']) == preview['body']: continue
            values = (sid, preview['base_revision']+1, encoded(preview['body']), preview['digest'], approval, now)
            cx.execute('INSERT OR REPLACE INTO resident_starting_maps VALUES(?,?,?,?,?,?)', values)
            cx.execute('INSERT INTO resident_starting_map_revisions VALUES(?,?,?,?,?,?)', values)
        return citation

    def staff(self, cx, iid, sid, title, role, instruction, approval):
        scope = 'institution.' + iid.split(':')[1]; now = int(time.time())
        old = cx.execute('SELECT instruction FROM profiles WHERE specialist_id=? ORDER BY revision DESC LIMIT 1', (sid,)).fetchone()
        cx.execute('INSERT OR IGNORE INTO specialists VALUES(?,?,?,?,?,?,?)', (sid, None, role, 'active', encoded(['studio']), now, approval))
        if approval.startswith('Owner Synod design approval '):
            cx.execute('UPDATE specialists SET role=? WHERE id=?', (role, sid))
        text = bounded(instruction + ' ' + STYLE, 1450, 'staff instructions')
        if not old or old[0] != text:
            rev = cx.execute('SELECT coalesce(max(revision),0)+1 FROM profiles WHERE specialist_id=?', (sid,)).fetchone()[0]
            cx.execute('INSERT INTO profiles VALUES(?,?,?,?,?)', (sid, rev, text, now, approval))
        cx.execute('INSERT OR IGNORE INTO grants VALUES(?,?)', (sid, scope))
        cx.execute('INSERT OR IGNORE INTO grants VALUES(?,?)', (sid, 'general'))
        cx.execute('INSERT OR REPLACE INTO institution_members VALUES(?,?,?)', (iid, sid, title))

    def append(self, cx, studio, commission, category, state, actor, body, evidence=(), event_key=None):
        if category not in CATEGORIES or state not in STATES:
            raise ValueError('Invalid archive category or status')
        if not isinstance(body, dict) or len(encoded(body).encode()) > 24000:
            raise ValueError('Archive record exceeds its bound')
        if not isinstance(evidence, (list, tuple)) or len(evidence) > 32:
            raise ValueError('Invalid archive evidence links')
        for ref in evidence:
            if not isinstance(ref, str) or not cx.execute('SELECT 1 FROM synod_records WHERE id=? AND studio=?', (ref, studio)).fetchone():
                raise PermissionError('Archive evidence must refer to a record in this dossier')
        if event_key:
            old = cx.execute('SELECT id FROM synod_records WHERE event_key=?', (event_key,)).fetchone()
            if old: return old[0]
        size = cx.execute('SELECT coalesce(sum(length(body)+length(evidence)),0) FROM synod_records').fetchone()[0]
        if size + len(encoded(body).encode()) > 64 * 1024 * 1024:
            raise ValueError('Synod archive budget reached; preserve and review before extending it')
        last = cx.execute('SELECT sequence,digest FROM synod_records WHERE studio=? ORDER BY sequence DESC LIMIT 1', (studio,)).fetchone()
        record = dict(id=ident('synod-record'), studio=studio, commission=commission,
                      sequence=last['sequence']+1 if last else 1, category=category, state=state,
                      actor=actor, body=body, evidence=list(evidence), previous=last['digest'] if last else '',
                      created=int(time.time()))
        digest = sha(encoded(record))
        cx.execute('INSERT INTO synod_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (record['id'], studio, commission, record['sequence'], category, state, actor,
                    encoded(body), encoded(list(evidence)), record['previous'], digest, event_key, record['created']))
        return record['id']

    def record(self, cx, ref, studio=None):
        row = cx.execute('SELECT * FROM synod_records WHERE id=?', (ref,)).fetchone()
        if not row or studio and row['studio'] != studio:
            raise PermissionError('Archive record unavailable in this dossier')
        out = dict(row); out['body'] = json.loads(out['body']); out['evidence'] = json.loads(out['evidence'])
        return out

    def commission(self, cx, ref):
        row = cx.execute('SELECT * FROM synod_commissions WHERE id=?', (ref,)).fetchone()
        if not row: raise ValueError('Synod commission unavailable')
        return dict(row)

    def dossier(self, cx, ref):
        rows = list(cx.execute('SELECT * FROM synod_dossiers WHERE id=? OR institution=?', (ref, ref)))
        if len(rows) != 1: raise ValueError('Choose a dossier or institution ID')
        return dict(rows[0])

    def create_commission(self, message, kind='create', studio=''):
        if kind not in ('create', 'repair'): raise ValueError('Choose create or repair')
        with self.store.db() as cx, cx:
            cx.execute('BEGIN IMMEDIATE')
            if kind == 'repair':
                if studio == SYNOD_ID or studio == SYNOD_STUDIO:
                    raise PermissionError('Changes to the built-in Synod require a reviewed repository change')
                try: dossier = self.dossier(cx, studio)
                except ValueError:
                    inst = self.store.institution(cx, studio)
                    dossier = dict(id=ident('synod-studio'), institution=inst['id'], name=inst['name'])
                    cx.execute('INSERT INTO synod_dossiers(id,institution,name,created) VALUES(?,?,?,?)',
                               (dossier['id'], inst['id'], inst['name'], int(time.time())))
                if cx.execute("SELECT 1 FROM synod_commissions WHERE studio=? AND state NOT IN ('complete','cancelled')", (dossier['id'],)).fetchone():
                    raise RuntimeError('This studio already has an open Synod commission')
            else:
                dossier = dict(id=ident('synod-studio'), name='Proposed studio')
                cx.execute('INSERT INTO synod_dossiers(id,name,created) VALUES(?,?,?)', (dossier['id'], dossier['name'], int(time.time())))
            ref = ident('synod-commission'); now = int(time.time())
            cx.execute('INSERT INTO synod_commissions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (ref, dossier['id'], kind, message['body'], message['id'], 'working', 'purpose', 0, '', '', '', now, now))
            self.append(cx, dossier['id'], ref, 'commission' if kind == 'create' else 'repair', 'proposed', message['sender'],
                        dict(request=message['body'], message=message['id'], thread=message['thread'], target=dossier.get('institution')), [])
            return self.commission(cx, ref)

    def search(self, studio, query='', category='', offset=0, limit=20):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Invalid archive page')
        if category and category not in CATEGORIES: raise ValueError('Invalid archive category')
        query = bounded(query, 200, 'archive query', empty=True); pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        with self.store.db() as cx:
            self.dossier(cx, studio)
            where = "studio=? AND (?='' OR category=?) AND body LIKE ? ESCAPE '\\'"
            args = (studio, category, category, pattern)
            total = cx.execute('SELECT count(*) FROM synod_records WHERE ' + where, args).fetchone()[0]
            rows = [dict(r) for r in cx.execute('SELECT id,commission,sequence,category,state,actor,digest,created,length(body) AS body_chars FROM synod_records WHERE ' + where + ' ORDER BY sequence DESC LIMIT ? OFFSET ?', (*args, limit, offset))]
        end = offset + len(rows)
        return dict(records=rows, total=total, offset=offset, next_offset=end if end < total else None)

    def read(self, studio, ref, start=0, chars=2000):
        if type(start) is not int or start < 0 or type(chars) is not int or not 1 <= chars <= 4000:
            raise ValueError('Invalid archive text range')
        with self.store.db() as cx: record = self.record(cx, ref, studio)
        body = encoded(record.pop('body')); record.pop('event_key', None)
        end = min(len(body), start + chars)
        return dict(record, text=body[start:end], start=start, total_chars=len(body), next_start=end if end < len(body) else None)

    def verify(self, studio):
        previous = ''; mismatches = []; sequence = 0
        with self.store.db() as cx:
            self.dossier(cx, studio)
            for row in cx.execute('SELECT * FROM synod_records WHERE studio=? ORDER BY sequence', (studio,)):
                record = dict(row); digest = record.pop('digest'); record.pop('event_key')
                record['body'] = json.loads(record['body']); record['evidence'] = json.loads(record['evidence'])
                sequence += 1
                if record['sequence'] != sequence or record['previous'] != previous or sha(encoded(record)) != digest:
                    mismatches.append(record['id'])
                previous = digest
        return dict(ok=not mismatches, records=sequence, head=previous, mismatches=mismatches)

    def view(self):
        with self.store.db() as cx:
            return dict(institution=SYNOD_ID, founding_required=False,
                        dossiers=[dict(r) for r in cx.execute('SELECT * FROM synod_dossiers ORDER BY created,id')],
                        commissions=[dict(r) for r in cx.execute('SELECT * FROM synod_commissions ORDER BY created DESC,rowid DESC LIMIT 100')],
                        targets=[dict(r) for r in cx.execute("SELECT id,name,purpose FROM institutions WHERE state='active' AND id<>? ORDER BY name", (SYNOD_ID,))],
                        packages=[dict(r) for r in cx.execute('SELECT institution,studio,state FROM synod_packages')],
                        supported_capabilities=['text'], specification_schema=SPEC_SCHEMA)

    def install(self, cx, commission):
        """Install only the exact owner-approved package, atomically and repeatably."""
        record = self.record(cx, commission['approved'], commission['studio'])
        spec = validate_spec(record['body']['spec'])
        missing = [c for c in spec['capabilities'] if c != 'text']
        if spec['founding_required']: missing.append('founding adapter')
        dossier = self.dossier(cx, commission['studio'])
        if any(row['id'] != dossier['institution'] and row['name'].casefold() == spec['name'].casefold()
               for row in cx.execute("SELECT id,name FROM institutions WHERE state='active'")):
            raise ValueError('A different active institution already uses this studio name')
        if dossier['institution'] and not cx.execute('SELECT 1 FROM synod_packages WHERE institution=?', (dossier['institution'],)).fetchone():
            missing.append('existing studio runtime repair adapter')
        if missing: raise ValueError('Construction requires implemented adapters: ' + ', '.join(missing))
        iid = dossier['institution'] or ident('institution'); scope = 'institution.' + iid.split(':')[1]; now = int(time.time())
        if not dossier['institution']:
            cx.execute('INSERT INTO institutions VALUES(?,?,?,?,?,?,?,?)',
                       (iid, spec['name'], 'studio', spec['purpose'], scope, encoded(dict(work_bytes=64*1024*1024)), 'active', now))
            cx.execute('INSERT INTO collections VALUES(?,?)', (scope, 'Private commissioned studio: ' + spec['name']))
        # Keep the previous live specification until the replacement passes trials.
        for key, title, role, instruction in [('lead', 'Studio Lead', 'analyst', spec['lead_instruction'])] + [
            (d['id'], d['title'], d['role'], d['instruction']) for d in spec['departments']]:
            sid = 'studio.' + iid.split(':')[1][:12] + '.' + key
            self.staff(cx, iid, sid, title, role, instruction, 'Owner Synod design approval ' + commission['id'])
        cx.execute('UPDATE synod_dossiers SET institution=?,name=? WHERE id=?', (iid, spec['name'], dossier['id']))
        if not cx.execute('SELECT 1 FROM synod_packages WHERE institution=?', (iid,)).fetchone():
            cx.execute('INSERT INTO synod_packages VALUES(?,?,?,?)', (iid, dossier['id'], record['id'], 'trial'))
        return dict(institution=iid, specification=record['id'], specification_sha256=sha(encoded(spec)),
                    runtime='bounded text workflow', dependencies=['local Captain model', 'Village SQLite'],
                    implementation=dict(database='village/village.sqlite', tables=['synod_packages','institution_members','synod_records','studio_jobs','studio_messages'],
                                        modules=['control/synod.py','control/synod_store.py'], resident_prefix='studio.'+iid.split(':')[1][:12]+'.'),
                    routing='studio_contact / Studio Lead inbox', founding_required=False)
