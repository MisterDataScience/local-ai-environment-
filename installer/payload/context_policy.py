"""Context hints for native clients; Ollama's tokenizer remains the hard boundary."""
from text_models import output_ceiling
from resource_modes import allowed
import re

THRESHOLDS = {'gaming': 1536, 'normal': 8192, 'max': 6144}
MIN_OLLAMA_VERSION = (0, 40, 0)


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
