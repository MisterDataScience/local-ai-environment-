"""Runs only in the private MLX environment. Stdout is PCM WAV, never logs."""
from contextlib import redirect_stdout
import io
import json
import sys
import wave


def main():
    data = json.load(sys.stdin)
    with redirect_stdout(sys.stderr):
        import mlx.core as mx
        import numpy as np
        from mlx_audio.tts.utils import load_model
        model = load_model(data['model'])
        if getattr(model.config, 'tts_model_type', None) != 'base' or model.sample_rate != 24000:
            raise ValueError('Expected the pinned Qwen3-TTS Base model at 24 kHz')
        if data.get('check_only'):
            print('Qwen3-TTS 1.7B Base: loaded on MLX')
            return
        chunks = []
        samples = 0
        for result in model.generate(text=data['text'], ref_audio=data['ref_audio'], ref_text=data['ref_text'],
                lang_code=data['language'], max_tokens=1500, split_pattern='\n', stream=False, verbose=False):
            mx.eval(result.audio)
            audio = np.asarray(result.audio).reshape(-1)
            if result.sample_rate != 24000 or not np.isfinite(audio).all():
                raise ValueError('Invalid model audio')
            samples += len(audio)
            if samples > 24000 * 120:
                raise ValueError('Speech exceeds two minutes; split the request')
            chunks.append(audio)
        if not chunks or not samples:
            raise ValueError('No speech returned')
        audio = np.concatenate(chunks)
        pcm = (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    sys.stdout.buffer.write(output.getvalue())


if __name__ == '__main__':
    main()
