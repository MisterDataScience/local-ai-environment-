import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_setup


class VoiceSetupTests(unittest.TestCase):
    def test_register_preserves_sample_and_refuses_overwrites_or_bad_ids(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); sample = root / 'sample.wav'
            with wave.open(str(sample), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
                wav.writeframes(b'\0\0' * 24000 * 4)
            voice_setup.register(root, 'default', sample, 'Hello world')
            self.assertEqual((root / 'voice-engine/voices/default.wav').read_bytes(), sample.read_bytes())
            self.assertEqual(json.loads((root / 'voice-engine/voices/default.json').read_text())['transcript'], 'Hello world')
            for voice in ['default', '../other']:
                with self.assertRaises(ValueError): voice_setup.register(root, voice, sample, 'Hello')
            with self.assertRaises(ValueError): voice_setup.register(root, 'new', sample, '')

    def test_install_pins_runtime_and_model_and_checks_load_before_marker(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); run = Mock()
            result = voice_setup.install(root, 'uv', run)
            self.assertTrue(result['enabled'])
            commands = [list(map(str, c.args[0])) for c in run.call_args_list]
            self.assertTrue(any('voice-macos-arm64-py312.txt' in ' '.join(c) and '--require-hashes' in c for c in commands))
            self.assertTrue(any('speech_worker.py' in ' '.join(c) for c in commands))
            self.assertEqual(json.loads((root / 'voice-engine/installed.json').read_text())['model_revision'], voice_setup.MODEL_REVISION)
