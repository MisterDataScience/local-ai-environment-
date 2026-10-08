import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scaffold_setup as setup
import essay_setup

class ScaffoldSetupTests(unittest.TestCase):
    def test_source_anchors_are_client_assigned_and_original_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'brief.txt';raw=b'AC 1.1 Explain distributions with examples.\r\n\r\nRules.';p.write_bytes(raw)
            result=setup.source_file(p,'B')
            self.assertEqual(result['anchors'][0]['id'],'B:p1')
            self.assertEqual(result['anchors'][0]['kind'],'criterion')
            self.assertEqual(result['anchors'][1]['text'],'Rules.')
            self.assertEqual(p.read_bytes(),raw)

    def test_guided_new_run_records_missing_inputs_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);brief=root/'brief.md';brief.write_text('Explain distributions.')
            with patch('builtins.input',side_effect=['','assignment',str(brief),'','yes','','','']):
                r=setup.prepare(root)
            self.assertTrue(r['brief_sufficient']);self.assertIsNone(r['word_count']);self.assertIsNone(r['referencing_style']);self.assertEqual(r['stage'],'1')

    def test_no_silent_approval_or_stage_advance(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'work-agent/state/reverse-scaffolds/test';folder.mkdir(parents=True)
            sha='a'*64
            (folder/'manifest.json').write_text(json.dumps({'approved':{},'pending':{sha:{'status':'AWAITING AUTHOR REVIEW','stage':'1','markdown':'review.md'}}}))
            with patch('builtins.input',side_effect=['','test','no']):
                with self.assertRaises(ValueError):setup.prepare(root)
            with patch('builtins.input',side_effect=['','test','approve']):
                r=setup.prepare(root)
            self.assertEqual(r,{'run_id':'test','stage':'approve','approve':[sha]})
