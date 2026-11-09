import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { validateContract, bindContract, assessResult, reviewBrief, nativeResultFormat } from '../handoff-contract.mjs';

const contract = (kind = 'analysis') => ({ facts: [], assumptions: [], unknowns: [], references: [],
  acceptance: [{ id: 'A1', requirement: 'Keep the feature', source_quote: 'Keep the feature',
    verification: { kind, command: kind === 'test' ? 'npm test' : '' } }] });
const result = () => ({ summary: 'Done', acceptance: [{ id: 'A1', status: 'met', evidence: 'Checked', tool_call_ids: ['call1'] }],
  tests: [], changed_files: [], assumptions: [], unresolved: [] });
const run = (kind, r, tools = []) => assessResult(contract(kind), JSON.stringify(r), tools);
const tool = (name = 'bash', exit = 0, command = 'npm test', status = 'completed') => ({ type: 'tool',
  tool: name, callID: 'call1', state: { status, input: { command }, metadata: { exit } } });

test('native format survives the pinned OpenCode runtime encoder', {
  skip: !process.env.LOCAL_AI_EFFECT_ROOT && 'Set LOCAL_AI_EFFECT_ROOT to effect@4.0.0-beta.83 for the real codec regression',
}, async () => {
  const root = resolve(process.env.LOCAL_AI_EFFECT_ROOT);
  const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
  assert.equal(pkg.version, '4.0.0-beta.83', 'Match OpenCode v1.18.34, not the latest Effect release');
  const {Effect, Schema} = await import(pathToFileURL(join(root, 'dist/index.js')).href);
  // Exact runtime fields from anomalyco/opencode v1.18.34:
  // packages/schema/src/v1/session.ts:65-78 and src/schema.ts:4.
  class OutputFormatText extends Schema.Class('OutputFormatText')({type: Schema.Literal('text')}) {}
  class OutputFormatJsonSchema extends Schema.Class('OutputFormatJsonSchema')({
    type: Schema.Literal('json_schema'),
    schema: Schema.Record(Schema.String, Schema.Any).annotate({identifier: 'JSONSchema'}),
    retryCount: Schema.Int.check(Schema.isGreaterThanOrEqualTo(0)).pipe(
      Schema.optional, Schema.withDecodingDefault(Effect.succeed(2))),
  }) {}
  const event = Schema.Struct({info: Schema.Struct({
    format: Schema.optional(Schema.Union([OutputFormatText, OutputFormatJsonSchema])),
  })});
  for (const readOnly of [false, true]) {
    const format = nativeResultFormat(contract('inspection'), readOnly);
    const wire = JSON.parse(JSON.stringify(format));
    assert.throws(() => Schema.encodeUnknownSync(event)({info: {format: wire}}),
      /Expected OutputFormatJsonSchema/, 'Reproduce the original native save failure');
    const encoded = Schema.encodeUnknownSync(event)({info: {format}});
    assert.deepEqual(encoded.info.format, wire);
    assert.deepEqual(Object.keys(encoded.info.format).sort(), ['retryCount', 'schema', 'type']);
    const decoded = Schema.decodeUnknownSync(event)(encoded);
    assert.equal(decoded.info.format instanceof OutputFormatJsonSchema, true);
    assert.equal(decoded.info.format.retryCount, 0);
    assert.deepEqual(decoded.info.format.schema, format.schema);
    format.retryCount = -1;
    assert.throws(() => Schema.encodeUnknownSync(event)({info: {format}}),
      /greater than or equal to 0/, 'Runtime field validation must remain active');
  }
});

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

test('the exact analyst result needs no execution IDs and remains a specialist claim', async () => {
  const saved = JSON.parse(await readFile(new URL('./fixtures/analyst-no-tool-ids.json', import.meta.url)));
  const report = assessResult(saved.contract, saved.raw_result, []);
  assert.equal(report.status, 'ready_for_review');
  assert.deepEqual(report.issues, []);
  assert.equal(report.acceptance[0].status, 'met');
  assert.equal(report.acceptance[0].basis, 'specialist_claim');
  assert.equal(report.raw_result, saved.raw_result);
  assert.deepEqual(report.observed_tools, []);
  assert(!Object.hasOwn(JSON.parse(report.raw_result).acceptance[0], 'tool_call_ids'));
});

test('only omitted analysis IDs are optional; malformed values remain invalid', () => {
  for (const value of [null, '', {}, [123]]) {
    const r = result(); r.acceptance[0].tool_call_ids = value;
    assert.equal(run('analysis', r).status, 'needs_attention');
  }
  const r = result(); delete r.acceptance[0].tool_call_ids;
  for (const kind of ['inspection', 'test'])
    assert.equal(run(kind, r, [tool('read'), tool('bash')]).status, 'needs_attention');
  r.tests = [{tool_call_id: 'unrun', command: 'npm test', status: 'passed'}];
  assert.equal(run('analysis', r).status, 'needs_attention', 'Analysis cannot waive an unrun test claim');
});

test('mixed acceptance keeps analysis claims separate from verified inspection evidence', () => {
  const c = contract('analysis');
  c.acceptance.push({...contract('inspection').acceptance[0], id: 'A2'});
  const r = result(); delete r.acceptance[0].tool_call_ids;
  r.acceptance.push({...result().acceptance[0], id: 'A2'});
  const report = assessResult(c, JSON.stringify(r), [tool('read')]);
  assert.equal(report.status, 'ready_for_review');
  assert.deepEqual(report.acceptance.map(row => row.basis), ['specialist_claim', 'native_inspection_recorded']);
  delete r.acceptance[1].tool_call_ids;
  assert.equal(assessResult(c, JSON.stringify(r), [tool('read')]).status, 'needs_attention');
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

test('failed inspection retains its native error and cannot satisfy the checklist', () => {
  const failed = tool('read', undefined, '', 'error');
  failed.state.error = 'Captain: native session operation failed';
  const report = run('inspection', result(), [failed]);
  assert.equal(report.status, 'needs_attention');
  assert.equal(report.acceptance[0].status, 'unverified');
  assert.equal(report.observed_tools[0].error, failed.state.error);
  assert.equal(report.observed_tools[0].error_truncated, false);
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

test('native commentary stays outside result evidence and requires full-report review', () => {
  const report = run('inspection', result(), [tool('read')]);
  report.native_final_text = 'An unverified extra claim.';
  report.native_final_text_status = 'unverified_commentary';
  const brief = reviewBrief(report);
  assert.equal(brief.status, 'ready_for_review');
  assert.equal(brief.full_report_required, true);
  assert(brief.report_read_reasons.includes('native_commentary_unverified'));
  assert(!JSON.stringify(brief).includes(report.native_final_text));
  assert.deepEqual(brief.tests, []);
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
