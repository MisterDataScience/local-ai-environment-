"""Context hints and bounded usage rollups; backend tokenizers own input limits."""
from text_models import output_ceiling
from resource_modes import allowed
import re
import json
import logging
import sqlite3
import threading
from contextlib import closing

THRESHOLDS = {'gaming': 1536, 'normal': 8192, 'max': 6144}
MIN_OLLAMA_VERSION = (0, 40, 0)
CLIENT_WORKFLOWS = frozenset({'captain', 'analyst', 'coder', 'document', 'essay', 'scaffold',
    'compaction', 'maintenance', 'batch', *('worker.' + role for role in ('researcher', 'analyst', 'coder', 'writer', 'reviewer'))})
STUDIO_WORKFLOWS = frozenset('studio.' + phase for phase in
    ('management', 'planning', 'middle', 'implementation', 'verification', 'founding', 'learning', 'synod', 'commissioned', 'other'))


def usage_label(body):
    """Caller hints are accounting labels, never permissions or host identities."""
    hint = body.get('usage_workflow')
    if body.get('_studio_turn') is not None:
        return (hint if isinstance(hint, str) and hint in STUDIO_WORKFLOWS else 'studio.other'), 'host'
    if body.get('_commons_turn') is not None:return 'commons', 'host'
    if body.get('_founding_turn') is not None:return 'founding', 'host'
    return (hint, 'client') if isinstance(hint, str) and hint in CLIENT_WORKFLOWS else ('chat', 'unclassified')


class UsageCounters:
    """Only fixed-label integer rollups are persisted; no request or response text."""
    FIELDS = ('requests', 'failed_requests', 'cutoff_requests',
        'prompt_measured_requests', 'completion_measured_requests',
        'measured_prompt_tokens', 'measured_completion_tokens',
        'prompt_estimated_requests', 'completion_estimated_requests',
        'estimated_prompt_tokens', 'estimated_completion_tokens',
        'prompt_unknown_requests', 'completion_unknown_requests')

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.unrecorded = 0

    def connect(self):
        if self.path.is_symlink():raise OSError('Usage database must not be a symbolic link')
        cx = sqlite3.connect(self.path, timeout=3)
        try:
            cx.row_factory = sqlite3.Row
            cx.execute('CREATE TABLE IF NOT EXISTS usage_rollups(workflow TEXT, source TEXT, mode TEXT, backend TEXT,'
                + ','.join(name + ' INTEGER NOT NULL' for name in self.FIELDS)
                + ',PRIMARY KEY(workflow,source,mode,backend))')
            return cx
        except Exception:
            cx.close(); raise

    @staticmethod
    def estimate(value):
        # A visible-text size heuristic, not a tokenizer or a context admission check.
        return (len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode(errors='replace')) + 3) // 4

    def record(self, body, mode, backend, messages, tools, output, counts, *, succeeded):
        workflow, source = usage_label(body)
        if mode not in THRESHOLDS or backend not in ('ollama', 'llama'):return
        counts = counts if isinstance(counts, dict) else {}
        values = dict.fromkeys(self.FIELDS, 0)
        values.update(requests=1, failed_requests=int(not succeeded), cutoff_requests=int(body.get('_finish_reason') == 'length'))
        for side, name, value in (('prompt', 'prompt_tokens', (messages, tools)),
                                  ('completion', 'completion_tokens', output)):
            count = counts.get(name)
            if type(count) is int and count >= 0:
                values[side + '_measured_requests'] = 1
                values['measured_' + name] = count
            elif succeeded and value is not None and not (side == 'prompt' and any(m.get('images') for m in messages)):
                values[side + '_estimated_requests'] = 1
                values['estimated_' + name] = self.estimate(value)
            else:
                values[side + '_unknown_requests'] = 1
        try:
            with self.lock, closing(self.connect()) as cx, cx:
                cx.execute('INSERT INTO usage_rollups VALUES(' + ','.join('?' for _ in range(4 + len(self.FIELDS)))
                    + ') ON CONFLICT(workflow,source,mode,backend) DO UPDATE SET '
                    + ','.join(name + '=' + name + '+excluded.' + name for name in self.FIELDS),
                    (workflow, source, mode, backend, *(values[name] for name in self.FIELDS)))
        except (OSError, sqlite3.Error):
            with self.lock:
                self.unrecorded += 1
                if self.unrecorded == 1:logging.warning('Token usage rollups could not be saved; inference continues.')

    def summary(self):
        with self.lock:
            try:
                with closing(self.connect()) as cx:
                    rows = [dict(r) for r in cx.execute('SELECT * FROM usage_rollups ORDER BY workflow,source,mode,backend')]
                available = True
            except (OSError, sqlite3.Error):rows = []; available = False
            return dict(version=1, storage_available=available, unrecorded_requests_since_start=self.unrecorded,
                scope='Cumulative recorded text-backend attempts; speech/media generation excluded.',
                measured_source='Backend-reported counts; input and output coverage are counted separately.',
                estimate_method='Completed responses only: UTF-8 JSON bytes divided by four, rounded up. '
                    'A text/tool size heuristic, not measured usage; image input and hidden reasoning are not estimated.',
                label_source='host=registered internal workflow; client=caller-reported agent hint; unclassified=no recognised hint.',
                totals={name: sum(row[name] for row in rows) for name in self.FIELDS}, workflows=rows)


def require_backend_version(version):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?', str(version))
    if not match or tuple(map(int, match.groups())) < MIN_OLLAMA_VERSION:
        raise RuntimeError('Context protection requires Ollama 0.40.0 or newer. Stop Local AI and rerun the updated installer.')
    return version


def compaction_policy(presets, mode):
    models = {}
    for identifier, preset in presets.items():
        if not allowed(mode, identifier, preset):
            continue
        context = min(preset['num_ctx'], 4096) if mode == 'gaming' else preset['num_ctx']
        output = output_ceiling(mode, preset)
        # Reserve output plus space for instructions, summaries and tool schemas.
        # This is a trigger for compaction, not an exact full-request token count.
        threshold = min(THRESHOLDS[mode], max(128, context - output - min(2048, context // 4)))
        models[identifier] = {'context': context, 'output': output, 'threshold': threshold}
    if not models:
        raise ValueError('No eligible text preset for context management')
    return {'mode': mode, 'models': models,
            # WebUI has a global cap, so use the smallest eligible budget.
            'threshold': min(m['threshold'] for m in models.values()),
            'summary_tokens': min(512 if mode == 'gaming' else 1024,
                                  min(m['context'] for m in models.values()) // 4)}
