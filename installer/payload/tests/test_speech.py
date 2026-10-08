import io
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import speech
from model_engine import Engine
from text_models import DEFAULT_TEXT_MODELS


def wav(seconds=4, rate=24000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(rate)
        audio.writeframes(b'\0\0' * rate * seconds)
    return output.getvalue()


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'control'; self.root.mkdir()
        self.folder = self.root.parent / 'voice-engine'
        (self.folder / 'voices').mkdir(parents=True)
        (self.folder / 'voices/default.wav').write_bytes(wav())
        (self.folder / 'voices/default.json').write_text(json.dumps({'transcript': 'Hello world'}))
        self.config = {'speech': {'enabled': True}, 'api_key': 'key', 'text_models': DEFAULT_TEXT_MODELS,
                       'public_url': 'http://127.0.0.1:8001'}
        self.engine = Engine(self.config, self.root)
        self.addCleanup(self.engine.executor.shutdown)
        self.addCleanup(self.temp.cleanup)

    def body(self):
        return {'model': 'local-ai-small', 'messages': [{'role': 'user', 'content': '/speak Hello there'}]}

    def test_reference_required_and_options_cannot_select_paths(self):
        for options in [{'voice': '../secret'}, {'language': []}, {'model': 'remote'}, {'voice': 'missing'}]:
            with self.assertRaises(ValueError): speech.request(self.config, self.root, 'Hello', options)
        with self.assertRaises(ValueError): speech.request({}, self.root, 'Hello')
        with self.assertRaises(ValueError): speech.request(self.config, self.root, 'x' * 2001)
        (self.folder / 'voices/default.wav').unlink()
        (self.folder / 'voices/default.wav').symlink_to('/does/not/exist')
        with self.assertRaises(ValueError): speech.request(self.config, self.root, 'Hello')

    def test_speech_unloads_text_and_uses_serial_queue(self):
        with patch('model_engine.port_open', return_value=False), patch.object(self.engine, 'stop_comfy'), \
             patch.object(self.engine, 'unload_ollama') as unload, patch('speech.generate', return_value='audio-link') as generate:
            self.assertEqual(self.engine.submit(self.body()).result(2), 'audio-link')
            unload.assert_called_once()
            self.assertEqual(generate.call_args.args[2]['ref_text'], 'Hello world')
        self.assertEqual(self.engine.state, 'idle')

    def test_gaming_and_stale_modes_block_speech(self):
        self.engine.mode = 'gaming'
        with self.assertRaises(ValueError): self.engine.submit(self.body())
        self.engine.mode = 'normal'
        body = self.body(); body['media_mode_token'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'mode changed'): self.engine.submit(body)

    def test_worker_is_offline_and_wav_is_saved_without_inheriting_keys(self):
        python = self.folder / '.venv/bin/python'; python.parent.mkdir(parents=True); python.touch()
        prepared = speech.request(self.config, self.root, 'Hello')
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'secret', 'GITHUB_TOKEN': 'secret'}), \
             patch('speech.subprocess.run', return_value=Mock(returncode=0, stdout=wav())) as run:
            link = speech.generate(self.config, self.root, prepared)
            self.assertIn('.wav)', link)
            env = run.call_args.kwargs['env']
            self.assertEqual(env['HF_HUB_OFFLINE'], '1')
            self.assertNotIn('GITHUB_TOKEN', env); self.assertNotIn('OPENAI_API_KEY', env)
        self.assertEqual(next((self.root / 'media').iterdir()).read_bytes(), wav())

    def test_invalid_or_failed_worker_never_saves_an_asset(self):
        python = self.folder / '.venv/bin/python'; python.parent.mkdir(parents=True); python.touch()
        prepared = speech.request(self.config, self.root, 'Hello')
        for code, content in [(1, b''), (0, b'not wav'), (0, wav(rate=8000))]:
            with patch('speech.subprocess.run', return_value=Mock(returncode=code, stdout=content)):
                with self.assertRaises(RuntimeError): speech.generate(self.config, self.root, prepared)
        self.assertEqual(list((self.root / 'media').iterdir()), [])

    def test_encrypted_audio_uses_atomic_vault_output(self):
        from contextlib import contextmanager
        python = self.folder / '.venv/bin/python'; python.parent.mkdir(parents=True); python.touch()
        output = io.BytesIO()
        @contextmanager
        def destination(config, suffix):
            self.assertEqual(suffix, '.wav'); yield output, 'a' * 32 + '.wav', None
        config = {**self.config, 'vault': {'enabled': True}}
        with patch('speech.subprocess.run', return_value=Mock(returncode=0, stdout=wav())), \
             patch('speech.vault_media.atomic_output', destination):
            speech.generate(config, self.root, speech.request(config, self.root, 'Hello'))
        self.assertEqual(output.getvalue(), wav())
        self.assertEqual(list((self.root / 'media').iterdir()), [])
