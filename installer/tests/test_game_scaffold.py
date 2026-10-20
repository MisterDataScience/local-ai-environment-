"""Structural and sufficiency contracts for adaptive reverse scaffolding."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import game_scaffold as g


def candidate(i):
    return dict(id='C'+str(i), title='Game '+str(i), player_experience='A specific player experience.',
        repeated_activity='Observe, choose, act, and respond to a changed world.', meaningful_choice='Choose between two routes with different consequences.',
        distinctive_hook='The world remembers the player choice.', demo_shape='One complete short playable loop.', uncertainty='Will players notice the changed world?')


def leaf(**overrides):
    value=dict(deliverable='A bounded movement rule specification for the designer.',
        instruction='Specify the movement rule, its states, transitions, and edge cases for this game.',
        inputs=['approved player promise', 'movement question'], outputs=['movement rule table'], depends_on=[],
        sufficiency_check='The table defines every state, transition, input and edge case required by the parent decision.',
        evidence=['rule table', 'one worked transition example'])
    value.update(overrides)
    return value


def review(verdict='accept', **overrides):
    checks=dict(contract_met=True, specific=True, traceable=True, complete_for_stage=True, checkable=True)
    findings=[]
    if verdict=='revise':
        checks['checkable']=False
        findings=['The proposed check has no observable output.']
    checks.update(overrides.pop('checks',{}))
    return dict(verdict=verdict, checks=checks, findings=findings, reason='The result is bounded and can be checked at this stage.')


class GameScaffoldTests(unittest.TestCase):
    def test_root_requires_broad_distinct_questions(self):
        c=[candidate(i) for i in range(1,5)]
        value=dict(selected_id='C1', title='Game 1', root_answer='Make a complete game around a specific player action and consequence.',
            contract={'player_goal':'Reach an ending.','repeated_play':'Choose and act.','intended_appeal':'Discover a rule.','demo_boundary':'One short loop.','completion_rule':'Reach the exit.','exclusions':'No campaign.'},
            first_questions=['How does a turn work?','What can change?','How is choice shown?','What ends the demo?','What makes the player return to play?'], rejected=[])
        self.assertEqual(g.selection(value,c)['selected_id'],'C1')

    def test_adaptive_split_allows_two_or_more_necessary_questions(self):
        split=dict(answer='This answer resolves the question enough to expose two consequential decisions that still need specific answers.', disposition='split',
            children=['Which state changes when the player acts?','How does the player perceive that changed state?'], leaf=None)
        self.assertEqual(g.expansion(split,dict(depth=1),0)['disposition'],'split')
        with self.assertRaisesRegex(ValueError,'two to five'):
            g.expansion({**split,'children':split['children'][:1]},dict(depth=1),0)

    def test_a_terminal_leaf_is_a_designer_deliverable_at_any_depth(self):
        result=dict(answer='This decision is resolved with one precise rule and no further consequential choice remains open.', disposition='leaf', children=[], leaf=leaf())
        self.assertEqual(g.expansion(result,dict(depth=1),0)['leaf']['deliverable'],leaf()['deliverable'])

    def test_leaf_requires_reviewable_result_and_evidence(self):
        result=dict(answer='This decision is resolved with one precise rule and no further consequential choice remains open.', disposition='leaf', children=[], leaf=leaf(outputs=[], evidence=[]))
        with self.assertRaisesRegex(ValueError,'reviewable output'):
            g.expansion(result,dict(depth=1),0)

    def test_audit_cannot_accept_failed_sufficiency_check(self):
        with self.assertRaisesRegex(ValueError,'cannot accept'):
            g.audit(review(checks={'specific':False}))
        self.assertEqual(g.audit(review())['verdict'],'accept')
        self.assertEqual(g.audit(review('revise'))['verdict'],'revise')

    def test_dependencies_must_reference_accepted_decision_leaves(self):
        accepted=dict(id='G0.1', state='leaf', audited=True, depth=1, leaf=leaf())
        current=dict(id='G0.2', state='queued', depth=1, leaf=leaf(depends_on=['G0.1']))
        self.assertEqual(g.validate_dependencies(current,[accepted]),[])
        current['leaf']['depends_on']=['missing']
        self.assertTrue(any('unknown prerequisite' in e for e in g.validate_dependencies(current,[accepted])))
        current['leaf']['depends_on']=['G0.1']
        accepted['audited']=False
        self.assertTrue(any('not an accepted' in e for e in g.validate_dependencies(current,[accepted])))

    def test_tree_shape_checks_links_and_acceptance_audit(self):
        root=dict(id='G0', parent=None, depth=0, state='split', children=['G0.1','G0.2','G0.3','G0.4','G0.5'], audited=True, audit=review())
        nodes=[root]
        for i in range(1,6):
            nodes.append(dict(id=f'G0.{i}',parent='G0',depth=1,question=f'Question {i}',answer='A sufficiently detailed answer to the design question.',state='leaf',children=[],audited=True,audit=review(),leaf=leaf()))
        state=g.initial_state({'mission':'make a game'});state['nodes']=nodes
        self.assertEqual(g.structural_errors(state),[])
        nodes[1]['leaf']['depends_on']=['missing']
        self.assertTrue(any('unknown prerequisite' in e for e in g.structural_errors(state)))

    def test_no_minimum_leaf_count_or_depth_is_encoded(self):
        self.assertFalse(hasattr(g,'MIN_LEAVES'))
        self.assertFalse(hasattr(g,'LEAF_DEPTH'))
        self.assertEqual(g.initial_state({})['version'],2)


if __name__=='__main__':
    unittest.main()
