"""Bounded local voice profiles and one-shot MLX speech worker."""
import io
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
import wave
import vault_media
from vault_tools import enabled as vault_enabled

MODEL_ID = 'mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16'
MODEL_REVISION = 'a6eb4f68e4b056f1215157bb696209bc82a6db48'
MLX_REVISION = '200aac3c64e5140dbe0daa4570dcb129f0f7afc9'
LANGUAGES = {'auto', 'English', 'Chinese', 'Japanese', 'Korean', 'German', 'French', 'Russian', 'Portuguese', 'Spanish', 'Italian'}
VOICE_ID = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')


def request(config, root, text, options=None):
    if not config.get('speech', {}).get('enabled'):
        raise ValueError('Speech is not installed. Rerun the updated installer.')
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Speech text must contain 1–2,000 characters.')
    options = options if options is not None else {}
    if not isinstance(options, dict) or set(options) - {'voice', 'language'}:
        raise ValueError('Speech accepts only a registered voice and language.')
    voice = options.get('voice', 'default')
    language = options.get('language', 'auto')
    if not isinstance(voice, str) or not VOICE_ID.fullmatch(voice) or not isinstance(language, str) or language not in LANGUAGES:
        raise ValueError('Invalid voice ID or language.')
    folder = root.parent / 'voice-engine/voices'
    profile_path = folder / (voice + '.json')
    if not profile_path.is_file() or profile_path.is_symlink():
        raise ValueError('Voice not registered. Run Configure Voice.command with a WAV sample and its transcript.')
    profile = json.loads(profile_path.read_text())
    audio = folder / (voice + '.wav')
    if not audio.is_file() or audio.is_symlink() or not isinstance(profile.get('transcript'), str) or not profile['transcript'].strip():
        raise ValueError('Invalid local voice profile.')
    return {'text': text.strip(), 'language': language, 'ref_audio': str(audio),
            'ref_text': profile['transcript'], 'model': str(root.parent / 'voice-engine/model')}


def validate_wav(content):
    if len(content) > 10_000_000:
        raise RuntimeError('Speech output exceeds the size limit.')
    try:
        with wave.open(io.BytesIO(content), 'rb') as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or rate != 24000 or not 0 < frames <= rate * 120:
                raise ValueError('Unexpected speech format or duration.')
            if len(audio.readframes(frames)) != frames * 2:
                raise ValueError('Incomplete audio.')
    except (wave.Error, EOFError, ValueError) as error:
        raise RuntimeError('Speech worker returned invalid audio.') from error


def generate(config, root, prepared):
    python = root.parent / 'voice-engine/.venv/bin/python'
    if not python.is_file():
        raise ValueError('Voice runtime missing. Rerun the updated installer.')
    allowed = {'HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR'}
    env = {k: v for k, v in os.environ.items() if k in allowed}
    env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
               PYTHONUNBUFFERED='1', TOKENIZERS_PARALLELISM='false')
    (root.parent / 'logs').mkdir(exist_ok=True, mode=0o700)
    # One process per request: exit releases MLX weights before the queue advances.
    with (root.parent / 'logs/speech.log').open('ab') as log:
        result = subprocess.run([str(python), str(root / 'speech_worker.py')],
            input=json.dumps(prepared).encode(), stdout=subprocess.PIPE, stderr=log,
            env=env, timeout=600, check=False)
    if result.returncode:
        raise RuntimeError('Speech generation failed. Check logs/speech.log.')
    validate_wav(result.stdout)
    if vault_enabled(config):
        with vault_media.atomic_output(config, '.wav') as (out, name, _):
            out.write(result.stdout)
    else:
        name = uuid.uuid4().hex + '.wav'
        path = root / 'media' / name
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(result.stdout)
    remote = config.get('remote_access', {})
    base = remote['media_url'] if remote.get('enabled') else config.get('public_url', 'http://127.0.0.1:8001')
    return f'[Play or download generated speech]({base}/media/{name})'
