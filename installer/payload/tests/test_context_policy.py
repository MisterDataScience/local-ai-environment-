import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_policy import compaction_policy, require_backend_version
from text_models import DEFAULT_TEXT_MODELS


class PolicyTests(unittest.TestCase):
    def test_thresholds_follow_mode_without_changing_model_contexts(self):
        source = copy.deepcopy(DEFAULT_TEXT_MODELS)
        for mode, threshold, summary in [('gaming', 1536, 512), ('normal', 8192, 1024), ('max', 6144, 1024)]:
            policy = compaction_policy(source, mode)
            self.assertEqual(policy['threshold'], threshold)
            self.assertEqual(policy['summary_tokens'], summary)
            if mode == 'gaming':
                self.assertEqual(set(policy['models']), {'local-ai-small'})
                self.assertEqual(policy['models']['local-ai-small']['context'], 4096)
            for model in policy['models'].values():
                self.assertLess(model['threshold'] + model['output'], model['context'])
        self.assertEqual(source, DEFAULT_TEXT_MODELS)

    def test_custom_smaller_context_reduces_global_cap_and_summary_budget(self):
        presets = copy.deepcopy(DEFAULT_TEXT_MODELS)
        presets['local-ai-small']['num_ctx'] = 4096
        policy = compaction_policy(presets, 'normal')
        self.assertEqual(policy['threshold'], 1024)
        presets['local-ai-small']['num_ctx'] = 512
        policy = compaction_policy(presets, 'normal')
        self.assertEqual(policy['threshold'], 128)
        self.assertEqual(policy['summary_tokens'], 128)

    def test_old_or_unknown_backends_cannot_claim_context_protection(self):
        for value in ('0.40.0', '0.41.1', 'v0.40.0', '0.40.0+build.1'):
            self.assertEqual(require_backend_version(value), value)
        for value in ('0.39.9', '0.9.0', None, '', 'unknown', '0.40'):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                require_backend_version(value)
