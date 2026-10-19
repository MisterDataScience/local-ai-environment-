"""Install and load-check the pinned local conversation components."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen

STT_MODEL = 'mlx-community/parakeet-tdt-0.6b-v3'
STT_REVISION = 'ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15'
VAD_REVISION = 'be95df9152c0d7618fa1edfeb296fc3dae32376f'
VAD_BLOB = '80c5592ef1f4c9ede3e357bbd02eb863358a6a9d'


def install(root, uv, run):
    sys.path.insert(0, str(Path(__file__).parent / 'payload'))
    from speech import MLX_REVISION
    folder = root / 'voice-engine'
    python = folder / '.venv/bin/python'
    from dependency_locks import install_locked
    dependency_receipt = install_locked(uv, python, 'voice', run)
    wanted = {'stt': STT_MODEL, 'stt_revision': STT_REVISION, 'vad_revision': VAD_REVISION,
              'vad_blob': VAD_BLOB, 'mlx_revision': MLX_REVISION, 'onnxruntime': '1.22.1', **dependency_receipt}
    marker = folder / 'conversation-installed.json'
    if (not marker.exists() or json.loads(marker.read_text()) != wanted
            or not (folder / 'stt/config.json').is_file() or not (folder / 'silero.onnx').is_file()):
        run([python, str(root / 'control/conversation_setup.py'), '--root', root, '--download'])
        env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
        for kind in ('vad', 'stt', 'tts'):
            run([python, str(root / 'control/conversation_worker.py'), kind, folder],
                input=b'{"check_only":true}\n', env=env, timeout=600)
        with (folder / 'conversation-dependencies.txt').open('w') as out:
            run([uv, 'pip', 'freeze', '--python', python], stdout=out)
        marker.write_text(json.dumps(wanted, indent=2) + '\n')
        marker.chmod(0o600)
    return {'enabled': True, **wanted}


def download(root):
    from huggingface_hub import snapshot_download
    folder = root / 'voice-engine'
    snapshot_download(STT_MODEL, revision=STT_REVISION, local_dir=folder / 'stt',
                      allow_patterns=['*.json', '*.safetensors', '*.txt', '*.model'])
    url = f'https://raw.githubusercontent.com/snakers4/silero-vad/{VAD_REVISION}/src/silero_vad/data/silero_vad.onnx'
    with urlopen(url, timeout=120) as response:
        data = response.read(5_000_001)
    digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if digest != VAD_BLOB:
        raise RuntimeError('Silero model checksum mismatch')
    (folder / 'silero.onnx').write_bytes(data)
    files = [folder / 'silero.onnx', *(folder / 'stt').rglob('*')]
    manifest = {}
    for path in files:
        if path.is_file() and '.cache' not in path.parts:
            sha = hashlib.sha256()
            with path.open('rb') as source:
                while block := source.read(8 * 1024 * 1024):
                    sha.update(block)
            manifest[str(path.relative_to(folder))] = {'size': path.stat().st_size, 'sha256': sha.hexdigest()}
    if not any(p.endswith('.safetensors') for p in manifest):
        raise RuntimeError('Transcription weights missing')
    (folder / 'conversation-artifacts.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--download', action='store_true', required=True)
    args = parser.parse_args()
    download(args.root)
