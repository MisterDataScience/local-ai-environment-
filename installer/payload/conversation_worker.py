"""Private resident audio workers; JSON lines on stdout, diagnostics on stderr."""
import base64
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import os
import threading
import time


def main():
    parent = os.getppid()
    def parent_watchdog():
        while True:
            time.sleep(2)
            if os.getppid() != parent:
                os._exit(1)
    threading.Thread(target=parent_watchdog, daemon=True).start()
    kind, folder = sys.argv[1], Path(sys.argv[2])
    output = sys.stdout
    def emit(value):
        output.write(json.dumps(value) + '\n')
        output.flush()
    with redirect_stdout(sys.stderr):
        import numpy as np
        if kind == 'vad':
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = opts.inter_op_num_threads = 1
            model = ort.InferenceSession(str(folder / 'silero.onnx'), sess_options=opts,
                                         providers=['CPUExecutionProvider'])
            state, context = np.zeros((2, 1, 128), np.float32), np.zeros((1, 64), np.float32)
        else:
            import mlx.core as mx
            mx.set_cache_limit(256 * 1024 * 1024)
            if kind == 'stt':
                from mlx_audio.stt.utils import load
                model = load(str(folder / 'stt'), model_type='parakeet')
                if model.preprocessor_config.sample_rate != 16000:
                    raise ValueError('Expected 16 kHz Parakeet')
            elif kind == 'tts':
                from mlx_audio.tts.utils import load_model
                model = load_model(str(folder / 'model'))
                if model.config.tts_model_type != 'base' or model.sample_rate != 24000:
                    raise ValueError('Expected Qwen3-TTS Base at 24 kHz')
            else:
                raise ValueError('Unknown audio worker')
        emit({'ready': True})
        for line in sys.stdin:
            try:
                data = json.loads(line)
                if data.get('check_only'):
                    emit({'done': True})
                    continue
                if kind in ('vad', 'stt'):
                    raw = base64.b64decode(data['pcm'], validate=True)
                    if not raw or len(raw) % 2 or len(raw) > 16000 * 2 * 30:
                        raise ValueError('Expected at most 30 seconds of PCM16 mono at 16 kHz')
                    audio = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768
                    if kind == 'vad':
                        if data.get('reset'):
                            state.fill(0)
                            context.fill(0)
                        if len(audio) % 512 or len(audio) > 8192:
                            raise ValueError('VAD requires complete 512-sample frames')
                        probabilities = []
                        for start in range(0, len(audio), 512):
                            x = np.concatenate((context, audio[start:start+512].reshape(1, -1)), axis=1)
                            prob, state = model.run(None, {'input': x, 'state': state, 'sr': np.array(16000, np.int64)})
                            context = x[:, -64:]
                            probabilities.append(float(prob.reshape(-1)[0]))
                        emit({'probabilities': probabilities})
                    else:
                        result = model.generate(mx.array(audio), verbose=False)
                        emit({'text': result.text.strip()})
                        mx.clear_cache()
                else:
                    samples = 0
                    for result in model.generate(text=data['text'], ref_audio=data['ref_audio'],
                            ref_text=data['ref_text'], lang_code=data['language'], max_tokens=1500,
                            stream=True, streaming_interval=.32, verbose=False):
                        mx.eval(result.audio)
                        audio = np.asarray(result.audio).reshape(-1)
                        samples += len(audio)
                        if result.sample_rate != 24000 or not np.isfinite(audio).all() or samples > 24000 * 120:
                            raise ValueError('Invalid or excessive speech output')
                        pcm = (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()
                        for offset in range(0, len(pcm), 24000):
                            emit({'pcm': base64.b64encode(pcm[offset:offset+24000]).decode(), 'sample_rate': 24000})
                    mx.clear_cache()
                emit({'done': True})
            except Exception as error:
                emit({'error': str(error), 'done': True})


if __name__ == '__main__':
    main()
