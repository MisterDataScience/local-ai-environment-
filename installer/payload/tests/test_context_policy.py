import copy
from pathlib import Path
import sys
import unittest
import json
import tempfile
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_policy import UsageCounters, usage_label, compaction_policy, require_backend_version
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


class UsageTests(unittest.TestCase):
    def test_durable_concurrent_rollups_store_counts_without_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'usage.sqlite'
            counters = UsageCounters(path)
            def record(_):
                counters.record({'usage_workflow': 'coder'}, 'normal', 'ollama',
                    [{'content': 'PRIVATE PROMPT'}], [], 'PRIVATE OUTPUT',
                    {'prompt_tokens': 20, 'completion_tokens': 7}, succeeded=True)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(record, range(40)))
            report = UsageCounters(path).summary()
            self.assertEqual(report['totals']['requests'], 40)
            self.assertEqual(report['totals']['measured_prompt_tokens'], 800)
            self.assertEqual(report['totals']['measured_completion_tokens'], 280)
            self.assertEqual(len(report['workflows']), 1)
            for secret in ('PRIVATE PROMPT', 'PRIVATE OUTPUT'):
                self.assertNotIn(secret, json.dumps(report))
                self.assertNotIn(secret.encode(), path.read_bytes())

    def test_partial_counts_images_and_failures_keep_separate_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            counters = UsageCounters(Path(folder) / 'usage.sqlite')
            counters.record({}, 'normal', 'llama', [{'content': 'hello'}], [], 'reply',
                {'prompt_tokens': 5, 'completion_tokens': True}, succeeded=True)
            counters.record({}, 'normal', 'llama', [{'images': ['image']}], [], '\ud800', {}, succeeded=True)
            counters.record({}, 'normal', 'llama', [], [], None,
                {'completion_tokens': 3}, succeeded=False)
            totals = counters.summary()['totals']
            self.assertEqual(totals['requests'], 3)
            self.assertEqual(totals['failed_requests'], 1)
            self.assertEqual(totals['measured_prompt_tokens'], 5)
            self.assertEqual(totals['measured_completion_tokens'], 3)
            self.assertEqual(totals['completion_estimated_requests'], 2)
            self.assertEqual(totals['prompt_unknown_requests'], 2)
            self.assertEqual(totals['estimated_prompt_tokens'], 0)

    def test_labels_are_fixed_and_host_guards_take_priority(self):
        self.assertEqual(usage_label({'usage_workflow': 'coder'}), ('coder', 'client'))
        self.assertEqual(usage_label({'usage_workflow': 'private-session-id'}), ('chat', 'unclassified'))
        self.assertEqual(usage_label({'usage_workflow': []}), ('chat', 'unclassified'))
        self.assertEqual(usage_label({'usage_workflow': 'studio.planning'}), ('chat', 'unclassified'))
        self.assertEqual(usage_label({'_studio_turn': object(), 'usage_workflow': 'studio.planning'}),
            ('studio.planning', 'host'))
        self.assertEqual(usage_label({'_commons_turn': object(), 'usage_workflow': 'coder'}), ('commons', 'host'))

    def test_storage_failure_is_reported_without_breaking_inference(self):
        counters = UsageCounters(Path('unused'))
        with patch.object(counters, 'connect', side_effect=sqlite3.OperationalError('unavailable')):
            counters.record({}, 'normal', 'ollama', [], [], 'reply', {}, succeeded=True)
            report = counters.summary()
        self.assertFalse(report['storage_available'])
        self.assertEqual(report['unrecorded_requests_since_start'], 1)
        self.assertEqual(report['totals']['requests'], 0)
