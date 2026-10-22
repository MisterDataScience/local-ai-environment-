import test from 'node:test';
import assert from 'node:assert/strict';
import { validateContract, bindContract, assessResult, reviewBrief } from '../handoff-contract.mjs';

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

test('complete short review briefs include criteria evidence and native test receipts', () => {
  const r = result(); r.tests = [{tool_call_id: 'call1', command: 'npm test', status: 'passed'}];
  const report = run('test', r, [tool()]);
  const brief = reviewBrief(report);
  assert.equal(brief.full_report_required, false);
  assert.equal(brief.acceptance[0].requirement, 'Keep the feature');
  assert.equal(brief.acceptance[0].evidence, 'Checked');
  assert.equal(brief.tests[0].command, 'npm test');
  assert.equal(brief.tests[0].execution_verified, true);
  assert.deepEqual(brief.report_read_reasons, []);
});

test('clipped evidence and unresolved results require full reports without altering saved evidence', () => {
  const r = result(); r.summary = 'Long summary '.repeat(200); r.acceptance[0].evidence = 'Source '.repeat(100);
  const report = run('analysis', r), before = JSON.stringify(report);
  const brief = reviewBrief(report);
  assert.equal(brief.full_report_required, true);
  assert(brief.report_read_reasons.includes('summary'));
  assert(brief.report_read_reasons.includes('evidence'));
  assert.equal(brief.acceptance[0].evidence.length, 400);
  assert.equal(JSON.stringify(report), before);
  const unresolved = reviewBrief(run('analysis', {...result(), unresolved: ['Needs reproduction']}));
  assert.equal(unresolved.full_report_required, true);
  assert.equal(unresolved.status, 'needs_attention');
  assert.deepEqual(unresolved.unresolved, ['Needs reproduction']);
});

test('the combined preview stays bounded with Unicode and preserves its need for detail', () => {
  const r = result();
  r.summary = '漢'.repeat(1600);
  r.assumptions = Array(4).fill('字'.repeat(240));
  r.changed_files = Array(8).fill('漢'.repeat(400));
  const report = run('analysis', r), brief = reviewBrief(report);
  assert.equal(brief.full_report_required, true);
  assert(brief.report_read_reasons.includes('oversized_brief'));
  assert.equal(brief.acceptance[0].status, 'met');
  assert(Buffer.byteLength(JSON.stringify(brief)) < 8000);
  assert.equal(report.summary, r.summary);
});
