"""Install pinned local TTS and register reference voices without model access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent / 'payload'))
from speech import MODEL_ID, MODEL_REVISION, MLX_REVISION, VOICE_ID


def install(root, uv, run):
    folder = root / 'voice-engine'
    folder.mkdir(exist_ok=True, mode=0o700)
    python = folder / '.venv/bin/python'
    if not python.exists():
        run([uv, 'venv', '--python', '3.12', folder / '.venv'])
    from dependency_locks import install_locked
    dependency_receipt = install_locked(uv, python, 'voice', run)
    marker = folder / 'installed.json'
    wanted = {'model': MODEL_ID, 'model_revision': MODEL_REVISION, 'mlx_revision': MLX_REVISION, **dependency_receipt}
    if not marker.exists() or json.loads(marker.read_text()) != wanted or not (folder / 'model/config.json').exists():
        run([python, str(root / 'control/voice_setup.py'), '--root', root, '--download'])
        env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
        run([python, str(root / 'control/speech_worker.py')],
            input=json.dumps({'model': str(folder / 'model'), 'check_only': True}).encode(), env=env, timeout=600)
        with (folder / 'dependencies.txt').open('w') as out:
            run([uv, 'pip', 'freeze', '--python', python], stdout=out)
        marker.write_text(json.dumps(wanted, indent=2) + '\n')
        marker.chmod(0o600)
    return {'enabled': True, **wanted}


def download_model(root):
    from huggingface_hub import snapshot_download
    target = root / 'voice-engine/model'
    snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_dir=target,
        allow_patterns=['*.json', '*.txt', '*.safetensors', 'speech_tokenizer/*'])
    artifacts = {}
    for file in target.rglob('*'):
        if not file.is_file() or '.cache' in file.parts:
            continue
        digest = hashlib.sha256()
        with file.open('rb') as source:
            while block := source.read(8 * 1024 * 1024): digest.update(block)
        artifacts[str(file.relative_to(target))] = {'size': file.stat().st_size, 'sha256': digest.hexdigest()}
    if not any(p.endswith('.safetensors') for p in artifacts):
        raise RuntimeError('Speech weights missing after download')
    (root / 'voice-engine/artifacts.json').write_text(json.dumps(artifacts, indent=2) + '\n')


def register(root, voice, source, transcript):
    if not VOICE_ID.fullmatch(voice) or not transcript.strip() or len(transcript) > 2000:
        raise ValueError('Use a simple voice ID and a transcript of 1–2,000 characters.')
    source = Path(source).expanduser()
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 10_000_000:
        raise ValueError('Select a regular PCM WAV file under 10 MB.')
    with wave.open(str(source), 'rb') as wav:
        duration = wav.getnframes() / wav.getframerate()
        if not 3 <= duration <= 30 or wav.getnchannels() not in (1, 2) or wav.getsampwidth() != 2:
            raise ValueError('Use a 3–30 second, mono/stereo, 16-bit PCM WAV reference.')
        content = source.read_bytes()
    folder = root / 'voice-engine/voices'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    audio, profile = folder / (voice + '.wav'), folder / (voice + '.json')
    if audio.exists() or profile.exists():
        raise ValueError('Voice ID already exists. Use a new ID; existing samples are preserved.')
    with audio.open('xb') as out: out.write(content)
    audio.chmod(0o600)
    try:
        with profile.open('x') as out: json.dump({'transcript': transcript.strip()}, out)
        profile.chmod(0o600)
    except Exception:
        audio.unlink()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    if args.download:
        download_model(args.root)
        return
    voice = input('Voice ID (Enter for default): ').strip() or 'default'
    source = input('Path to a clean 3–30 second PCM WAV reference: ').strip()
    transcript = input('Exact words spoken in that reference: ').strip()
    register(args.root, voice, source, transcript)
    print('Voice registered locally. Restart Local AI, then use /speak YOUR TEXT for the default voice.')
    print('Reference samples and transcripts are local plaintext in voice-engine/voices, outside the vault.')


if __name__ == '__main__':
    try: main()
    except Exception as error: raise SystemExit('Voice setup stopped: ' + str(error))
