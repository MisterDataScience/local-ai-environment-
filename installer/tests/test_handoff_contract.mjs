import test from 'node:test';
import assert from 'node:assert/strict';
import { validateContract, bindContract, assessResult } from '../handoff-contract.mjs';

const contract = (kind = 'analysis') => ({ facts: [], assumptions: [], unknowns: [], references: [],
  acceptance: [{ id: 'A1', requirement: 'Keep the feature', source_quote: 'Keep the feature',
    verification: { kind, command: kind === 'test' ? 'npm test' : '' } }] });
const result = () => ({ summary: 'Done', acceptance: [{ id: 'A1', status: 'met', evidence: 'Checked', tool_call_ids: ['call1'] }],
  tests: [], changed_files: [], assumptions: [], unresolved: [] });
const run = (kind, r, tools = []) => assessResult(contract(kind), JSON.stringify(r), tools);
const tool = (name = 'bash', exit = 0, command = 'npm test', status = 'completed') => ({ type: 'tool',
  tool: name, callID: 'call1', state: { status, input: { command }, metadata: { exit } } });

test('quotes are exact and bound only to supplied explicit user text', () => {
  const c = contract(); validateContract(c);
  const messages = [{ info: { id: 'u1' }, parts: [{ type: 'text', text: 'Please: Keep the feature' }] }];
  assert.equal(bindContract(c, messages).acceptance[0].source.message_id, 'u1');
  assert.throws(() => bindContract(c, []), /explicit user/);
  messages[0].parts[0].synthetic = true;
  assert.throws(() => bindContract(c, messages), /explicit user/);
  c.acceptance[0].requirement = 'Change it';
  assert.throws(() => validateContract(c), /verbatim/);
});

test('derived requirements are labelled and references reject traversal', () => {
  const c = contract(); c.acceptance[0].source_quote = '';
  assert.equal(bindContract(c, []).acceptance[0].source.kind, 'derived');
  c.references = [{ path: '../secret', symbol: '' }];
  assert.throws(() => validateContract(c), /relative project/);
});

test('analysis is a claim, not independently verified correctness', () => {
  const report = run('analysis', result());
  assert.equal(report.status, 'ready_for_review');
  assert.equal(report.acceptance[0].basis, 'specialist_claim');
});

test('missing duplicate and unknown criterion returns need attention', () => {
  for (const rows of [[], [result().acceptance[0], result().acceptance[0]], [{ ...result().acceptance[0], id: 'A2' }]]) {
    assert.equal(run('analysis', { ...result(), acceptance: rows }).status, 'needs_attention');
  }
});

test('test success needs an exact actual command and zero exit', () => {
  const r = result(); r.tests = [{ tool_call_id: 'call1', command: 'npm test', status: 'passed' }];
  for (const tools of [[], [tool('bash', 1)], [tool('bash', null)], [tool('bash', 0, 'echo pass')], [tool('bash', 0, 'npm test', 'error')]]) {
    assert.equal(run('test', r, tools).status, 'needs_attention');
  }
  const report = run('test', r, [tool()]);
  assert.equal(report.status, 'ready_for_review');
  assert.equal(report.acceptance[0].basis, 'native_command_exit_zero');
});

test('inspection requires a linked successful native inspection', () => {
  assert.equal(run('inspection', result()).status, 'needs_attention');
  assert.equal(run('inspection', result(), [tool('read')]).status, 'ready_for_review');
});

test('unresolved issues and malformed output cannot pass', () => {
  assert.equal(run('analysis', { ...result(), unresolved: ['Still broken'] }).status, 'needs_attention');
  assert.equal(assessResult(contract(), 'plain text', []).status, 'needs_attention');
});
