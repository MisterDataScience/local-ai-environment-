"""Guided local input and exact-version author approvals. No model or web calls."""
import json
from pathlib import Path
import re

STAGES = ['1', '2', '3', '4', '5', '6', '7A', '7C', '8', '9']


def read_json(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 200000:
        raise ValueError('Choose a regular JSON file under 200 KB')
    return json.loads(path.read_text())


def source_file(path, identifier, kind='brief', metadata=None):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {'.txt', '.md'} or path.stat().st_size > 120000:
        raise ValueError('Choose a regular UTF-8 .txt or .md source under 120 KB')
    text = path.read_bytes().decode('utf-8')
    paragraphs = [p for p in re.split(r'\r?\n[ \t]*\r?\n', text) if p.strip()]
    if not paragraphs: raise ValueError('Source is empty')
    anchors = []
    for i, paragraph in enumerate(paragraphs, 1):
        anchor_kind = 'passage' if kind == 'reference' else 'context'
        if kind in {'brief','spec','rules'} and re.match(r'^\s*(?:AC\s*)?\d+\.\d+\s*[.:-]?\s*(?:explain|analyse|assess|evaluate|describe|discuss|compare|critically)',paragraph,re.I):
            anchor_kind = 'criterion'
        anchors.append({'id':f'{identifier}:p{i}', 'text':paragraph, 'kind':anchor_kind})
    result = {'id':identifier,'kind':kind,'title':path.name,'location':str(path.resolve()),'anchors':anchors}
    if metadata:
        result.update({k:metadata[k] for k in ('reference','verified_metadata','title') if k in metadata})
    return result


def prepare(root):
    packet = input('Scaffold request JSON path, or Enter for guided setup: ').strip()
    if packet:
        request = read_json(packet)
        if not isinstance(request,dict): raise ValueError('Request must be a JSON object')
        return request
    run = input('Scaffold run name (new or existing, lower-case letters/numbers/hyphens): ').strip()
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',run): raise ValueError('Invalid run name')
    directory = root / 'work-agent/state/reverse-scaffolds' / run
    manifest = directory / 'manifest.json'
    if not manifest.exists():
        brief = source_file(input('Official brief (.txt or .md) path: ').strip(),'BRIEF')
        sources=[brief]
        spec = input('Unit specification path, or Enter if absent: ').strip()
        if spec: sources.append(source_file(spec,'SPEC','spec'))
        sufficient = bool(spec)
        if not spec:
            sufficient = input('Does the brief independently establish the task? Type yes to confirm: ').strip().lower()=='yes'
            if not sufficient: raise ValueError('Supply the required unit specification before starting')
        rules = input('Additional marking/submission rules path, or Enter if absent: ').strip()
        if rules:sources.append(source_file(rules,'RULES','rules'))
        total = input('Allowed main-text word count, or Enter if not supplied: ').strip()
        style = input('Required referencing style, or Enter if not supplied: ').strip()
        return {'run_id':run,'stage':'1','sources':sources,'word_count':int(total) if total else None,
                'referencing_style':style or None,'brief_sufficient':sufficient,'depends_on_spec':bool(spec)}
    state = read_json(manifest)
    approved = {v['sha'] for v in state['approved'].values()}
    pending = [(sha,p) for sha,p in state['pending'].items() if sha not in approved and p['status']=='AWAITING AUTHOR REVIEW']
    if pending:
        sha,item = pending[-1]
        print('Review this stage before approving:', item['markdown'])
        print('Exact approval hash:',sha)
        if input('Type approve only after reviewing this exact version: ').strip()!='approve':
            raise ValueError('Stage left unapproved; no later stage was started')
        return {'run_id':run,'stage':'approve','approve':[sha]}
    next_stage = next((s for s in STAGES if s not in state['approved']),None)
    if next_stage is None: raise ValueError('All stages are approved; use an explicit request JSON for a revision or new progress check')
    failed = [x for x in state['pending'].values() if x['stage']==next_stage and x['status']!='AWAITING AUTHOR REVIEW']
    if failed:
        print('Last incomplete/blocked stage:',failed[-1]['markdown'])
        raise ValueError('Review the failed checks. Supply an explicit corrected request JSON; do not silently retry unchanged work')
    request = {'run_id':run,'stage':next_stage}
    print('Requested stage:',next_stage,'Only this stage will run.')
    if next_stage=='7C':
        entries = read_json(input('Checked reference list JSON path (id, path, reference, verified_metadata): ').strip())
        if not isinstance(entries,list): raise ValueError('Reference list must be an array')
        request['sources']=[source_file(x['path'],x['id'],'reference',x) for x in entries]
    if next_stage=='9':
        request['answers']=read_json(input('Author answers JSON path (question ID to answer text): ').strip())
    return request
