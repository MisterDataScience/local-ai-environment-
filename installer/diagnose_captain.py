"""One existing-model text probe. No installs, config edits or readiness receipts."""
import argparse
import json
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parent
if (SOURCE / 'payload').is_dir():
    sys.path.insert(0, str(SOURCE / 'payload'))

from backend_http import api, port_open
from feature_state import atomic_json, installation_lock
from native_diagnostics import capture, diagnostic_path
from shared_llama import SharedLlama
from text_models import output_ceiling
from turnkey_install import ReadinessError

PROMPT = 'Reply with one sentence about Python.'


def diagnose(root):
    """Capture one generation through the same request builder as the gateway."""
    root = Path(root).resolve(strict=True)
    with installation_lock(root):
        if port_open(8001) or port_open(11437):
            raise ReadinessError('Stop Local AI before this diagnostic; no running service was stopped')
        config = json.loads((root / 'control/config.json').read_text())
        captain = config.get('captain', {})
        if not captain.get('enabled') or captain.get('provider') != 'llama':
            raise ReadinessError('Configured Captain does not select the native GGUF backend')
        identifier = captain['model_id']
        preset = dict(config['text_models'][identifier], thinking=True)
        limit = output_ceiling('max', preset)
        check = 'captain-text-probe'
        path = diagnostic_path(root, check)
        raw_path = diagnostic_path(root, check + '-raw')
        native_log = root / 'logs/native-acceptance/captain-probe-runtime.log'
        backend = SharedLlama(captain, native_log)
        body = {'model': identifier, 'messages': [{'role': 'user', 'content': PROMPT}], 'stream': False}
        atomic_json(path, {'check': check, 'model_id': identifier, 'thinking': True,
                          'status': 'testing', 'stage': 'model_startup'})

        def request():
            # The production builder supplies system instructions. Capture its
            # actual fixed-fixture request and response in one inference call.
            def record(base, endpoint, payload, **kwargs):
                raw = api(base, endpoint, payload, **kwargs)
                atomic_json(raw_path, {'model_id': identifier, 'fixture_prompt': PROMPT, 'thinking': True,
                    'parallel_slots': 1, 'max_tokens': limit,
                    'request': {k: payload[k] for k in ('model', 'messages', 'stream', 'max_tokens', 'cache_prompt') if k in payload},
                    'response': {k: raw[k] for k in ('model', 'choices', 'usage', 'timings') if k in raw}})
                return raw
            result = backend.chat(body, limit, transport=record)
            message = {'role': 'assistant', 'content': result} if isinstance(result, str) else result
            return {'model': identifier, 'choices': [{'message': message,
                'finish_reason': body.get('_finish_reason', 'stop')}], 'usage': body.get('_usage', {})}

        failure = None
        cleanup_failure = None
        try:
            backend.start(preset['num_ctx'], thinking=True, parallel=1)
            capture(root, check, identifier, preset, request, prompt=PROMPT)
        except Exception as error:
            failure = error
            row = json.loads(path.read_text())
            if row.get('status') == 'testing':
                row.update(status='failed', issue='probe_failed', error_type=type(error).__name__)
                atomic_json(path, row)
        finally:
            try:
                backend.stop()
            except Exception as error:
                cleanup_failure = type(error).__name__
        row = json.loads(path.read_text())
        summary = {k: row[k] for k in ('status', 'stage', 'issue', 'model_id', 'thinking',
                    'finish_reason', 'final_chars', 'reasoning_chars', 'error_type') if k in row}
        summary.update(diagnostic=str(path), raw_response=str(raw_path), native_log=str(native_log),
                       scope='One text-generation probe with one decode slot; not full installation acceptance.')
        if cleanup_failure:
            summary['shutdown_error'] = cleanup_failure
        try:
            final = row['response']['choices'][0]['message']['content']
            summary['final_text'] = final[:2000] if isinstance(final, str) else final
        except (KeyError, IndexError, TypeError):
            pass
        atomic_json(diagnostic_path(root, check + '-summary'), summary)
        print(json.dumps(summary, indent=2))
        return 1 if failure or cleanup_failure else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        return diagnose(args.root)
    except ReadinessError as error:
        print(str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
