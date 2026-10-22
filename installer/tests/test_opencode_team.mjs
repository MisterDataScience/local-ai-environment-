import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import LocalTeam from '../opencode-team.mjs';

async function fixture(t) {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ instance_id: 'backend', epoch: 0, mode: 'normal' }) });
  t.after(() => { globalThis.fetch = previousFetch; });
  const root = await mkdtemp(join(tmpdir(), 'local-team-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const ledgerPath = join(root, 'budget.json');
  await writeFile(ledgerPath, JSON.stringify({ version: 1, turns: {} }));
  const messages = [{ info: { id: 'user1', role: 'user' }, parts: [{ type: 'text', text: 'Task' }] }];
  const session = { id: 'session1' };
  const client = { session: {
    get: async () => ({ data: session }), messages: async () => ({ data: messages }),
  }};
  const options = { ledgerPath, modeToken: 'backend:0:normal', roles: { coordinator: 'coord', analyst: 'analysis', coder: 'code', document: 'doc', essay_document: 'doc', scaffold_document: 'doc' } };
  const hooks = await LocalTeam({ client, directory: root }, options);
  await hooks['chat.message']({ sessionID: 'session1' }, { message: messages[0].info, parts: messages[0].parts });
  function call(id, role = 'analyst', extra = {}, parent = 'user1') {
    messages.push({ info: { id: 'assistant-' + id, role: 'assistant', parentID: parent, agent: 'plan' },
      parts: [{ id: 'part-' + id, type: 'tool', tool: 'task', callID: id, state: { status: 'running' } }] });
    return [{ tool: 'task', sessionID: 'session1', callID: id }, { args: {
      subagent_type: role, description: 'Focused task', prompt: JSON.stringify({ objective: 'Solve',
      constraints: 'Use evidence', evidence: 'src/a.py: @file is literal', completed: '', remaining: '',
      result: 'Answer and validation', facts: [], assumptions: [], unknowns: [], references: [],
      acceptance: [{ id: 'A1', requirement: 'Task', source_quote: 'Task', verification: { kind: 'analysis', command: '' } }], ...extra }),
    }}];
  }
  const before = (args) => hooks['tool.execute.before'](...args);
  async function after(args, text = 'Result') {
    const output = { output: text, metadata: {} };
    await hooks['tool.execute.after'](args[0], output);
    return output;
  }
  return { hooks, call, before, after, client, options, messages, session, ledgerPath, directory: root };
}

test('two bounded native handoffs, literal evidence, then stop', async t => {
  const f = await fixture(t);
  const first = f.call('one'); await f.before(first);
  assert(!first[1].args.prompt.includes('@'));
  assert(JSON.parse(first[1].args.prompt).evidence.includes('@file'));
  await f.after(first);
  const second = f.call('two', 'coder'); await f.before(second); await f.after(second);
  await assert.rejects(f.before(f.call('three')), /two specialist attempts/);
  assert.equal(Object.values(JSON.parse(await readFile(f.ledgerPath)).turns)[0].calls.length, 2);
});

test('parallel requests and duplicate calls cannot oversubscribe', async t => {
  const f = await fixture(t);
  const one = f.call('one'), two = f.call('two', 'coder');
  const results = await Promise.allSettled([f.before(one), f.before(two)]);
  assert.equal(results.filter(r => r.status === 'fulfilled').length, 1);
  await assert.rejects(f.before(one), /duplicate call/);
  await f.after(one); await f.before(two); await f.after(two);
});

test('one retry requires concrete failure and consumes second attempt', async t => {
  const f = await fixture(t);
  const first = f.call('one'); await f.before(first); await f.after(first);
  await assert.rejects(f.before(f.call('bad-retry')), /concrete failure/);
  const retry = f.call('retry', 'analyst', { retry_failure: 'Returned an inconsistent total: 2+2=5' });
  await f.before(retry); await f.after(retry);
  await assert.rejects(f.before(f.call('three', 'coder')), /two specialist attempts/);
});

test('errors consume attempts, native error status releases serial gate', async t => {
  const f = await fixture(t);
  await f.before(f.call('one'));
  f.messages[1].parts[0].state.status = 'error';
  const second = f.call('two', 'coder'); await f.before(second); await f.after(second);
  await assert.rejects(f.before(f.call('three')), /two specialist attempts/);
});

test('retry cannot weaken the saved acceptance checklist', async t => {
  const f = await fixture(t), first = f.call('one');
  await f.before(first); await f.after(first);
  const retry = f.call('retry', 'analyst', { retry_failure: 'The answer was incorrect',
    acceptance: [{ id: 'A1', requirement: 'Something easier', source_quote: '', verification: { kind: 'analysis', command: '' } }] });
  await assert.rejects(f.before(retry), /preserve the original acceptance/);
  assert.equal(Object.values(JSON.parse(await readFile(f.ledgerPath)).turns)[0].calls.length, 1);
});

test('reconnected hooks share persisted accounting and native turn identity', async t => {
  const f = await fixture(t);
  const one = f.call('one'); await f.before(one); await f.after(one);
  const hooks = await LocalTeam({ client: f.client, directory: f.directory }, f.options);
  const two = f.call('two', 'coder'); await hooks['tool.execute.before'](...two);
  await hooks['tool.execute.after'](two[0], { output: 'Result', metadata: {} });
  await assert.rejects(f.before(f.call('three')), /two specialist attempts/);
  f.messages.push({ info: { role: 'user', id: 'user2' }, parts: [{ type: 'text', text: 'New task' }] });
  await f.hooks['chat.message']({ sessionID: 'session1' }, { message: f.messages.at(-1).info, parts: f.messages.at(-1).parts });
  await f.before(f.call('new', 'coder', {}, 'user2'));
});

test('compaction continuation does not reset budget', async t => {
  const f = await fixture(t);
  for (const [id, role] of [['one', 'analyst'], ['two', 'coder']]) {
    const args = f.call(id, role); await f.before(args); await f.after(args);
  }
  f.messages.push({ info: { role: 'user', id: 'synthetic' }, parts: [{ type: 'text', text: 'Continue', synthetic: true }] });
  await assert.rejects(f.before(f.call('three', 'coder', {}, 'synthetic')), /two specialist attempts/);
  f.messages.push({ info: { role: 'user', id: 'replay' }, parts: [{ type: 'text', text: 'Task' }] });
  await assert.rejects(f.before(f.call('four', 'coder', {}, 'replay')), /two specialist attempts/);
});

test('nested delegation, child tools and implicit attachments are blocked', async t => {
  const f = await fixture(t); f.session.parentID = 'parent';
  await assert.rejects(f.before(f.call('one')), /cannot use tools/);
  await assert.rejects(f.hooks['tool.execute.before']({ tool: 'bash', sessionID: 'session1' }, { args: {} }), /cannot use tools/);
  await assert.rejects(f.hooks['chat.message']({ sessionID: 'session1' }, { parts: [{ type: 'file' }] }), /supplied text/);
});

test('role, resume, background, unknown identity and malformed envelopes fail', async t => {
  const f = await fixture(t);
  await assert.rejects(f.before(f.call('unknown', 'general')), /analyst, coder/);
  for (const extra of [{ task_id: 'session-other' }, { background: true }, { command: 'shell' }]) {
    const args = f.call('bad'); Object.assign(args[1].args, extra);
    await assert.rejects(f.before(args), /disabled/);
  }
  const malformed = f.call('json'); malformed[1].args.prompt = 'not json';
  await assert.rejects(f.before(malformed), /JSON/);
  const oversized = f.call('large', 'coder', { evidence: 'x'.repeat(12001) });
  await assert.rejects(f.before(oversized), /12000/);
  const missing = f.call('missing'); f.messages.pop();
  await assert.rejects(f.before(missing), /native assistant message/);
});

test('configuration enables only named specialists and rejects role model changes', async t => {
  const f = await fixture(t);
  const config = { tools: { task: false }, agent: { plan: { permission: {} }, build: { permission: {} } } };
  await f.hooks.config(config);
  assert.equal(config.tools.task, true);
  assert.equal(config.tools.local_video, false);
  assert.equal(config.agent.plan.permission.local_video, 'deny');
  assert.deepEqual(config.agent.plan.permission.task, { '*': 'deny', analyst: 'allow', coder: 'allow', document: 'allow', essay_document: 'allow', scaffold_document: 'allow' });
  await f.hooks['chat.params']({ agent: 'coder', model: { providerID: 'local-ai-gateway', id: 'code' } });
  await assert.rejects(f.hooks['chat.params']({ agent: 'coder', model: { providerID: 'cloud', id: 'code' } }), /model changed/);
});

test('Max exposes video while ordinary turns carry no document workflow directive', async t => {
  const f = await fixture(t);
  assert(!f.messages[0].parts.some(p => p.synthetic));
  const hooks = await LocalTeam({client: f.client, directory: f.directory},
    {...f.options, modeToken: 'backend:0:max'});
  const config = {tools: {}, agent: {plan: {permission: {}}, build: {permission: {}}}};
  await hooks.config(config);
  assert.equal(config.tools.local_video, true);
  assert.equal(config.agent.build.permission.local_video, 'ask');
});

test('oversized results are preserved in a recoverable full report', async t => {
  const f = await fixture(t), args = f.call('one'); await f.before(args);
  const result = await f.after(args, 'x'.repeat(15000));
  const brief = JSON.parse(result.output);
  assert.equal(brief.status, 'needs_attention');
  assert.equal(brief.full_report_required, true);
  assert.equal(JSON.parse(await readFile(brief.full_report, 'utf8')).raw_result, 'x'.repeat(15000));
  assert(result.output.length < 3000);
});

test('fresh process state recovers exhausted budget and interrupted attempts', async t => {
  const f = await fixture(t);
  const args = f.call('one'); await f.before(args); await f.after(args);
  const two = f.call('two', 'coder'); await f.before(two);
  // A distinct module instance represents a fresh process, with the same disk state.
  const fresh = (await import('../opencode-team.mjs?restart=' + Date.now())).default;
  const hooks = await fresh({ client: f.client, directory: f.directory }, f.options);
  await assert.rejects(hooks['tool.execute.before'](...f.call('third')), /two specialist attempts/);
  assert.equal(Object.values(JSON.parse(await readFile(f.ledgerPath)).turns)[0].calls[1].status, 'interrupted');
});

test('mode changes, gateway restarts and unavailable status block delegation', async t => {
  const f = await fixture(t);
  for (const status of [{ instance_id: 'backend', epoch: 1, mode: 'normal' },
    { instance_id: 'new-backend', epoch: 0, mode: 'normal' },
    { instance_id: 'backend', epoch: 0, mode: 'gaming' }]) {
    globalThis.fetch = async () => ({ ok: true, json: async () => status });
    await assert.rejects(f.before(f.call('stale')), /mode changed or restarted/);
  }
  globalThis.fetch = async () => ({ ok: false });
  await assert.rejects(f.before(f.call('offline')), /mode unavailable/);
  assert.equal(Object.values(JSON.parse(await readFile(f.ledgerPath)).turns)[0].calls.length, 0);
});

async function coderFixture(t, parentAgent = 'build') {
  const f = await fixture(t);
  const handoff = f.call('delegate', 'coder');
  f.messages.at(-1).info.agent = parentAgent;
  await f.before(handoff);
  f.messages.at(-1).parts[0].state.metadata = { sessionId: 'child' };
  const child = { id: 'child', parentID: 'session1' };
  const childMessages = [];
  f.client.session.get = async ({ path }) => ({ data: path.id === 'child' ? child : f.session });
  f.client.session.messages = async ({ path }) => ({ data: path.id === 'child' ? childMessages : f.messages });
  async function use(tool, agent = 'coder') {
    const callID = 'tool-' + childMessages.length;
    childMessages.push({ info: { id: 'message-' + callID, role: 'assistant', agent },
      parts: [{ type: 'tool', tool, callID, state: { status: 'running' } }] });
    const output = { args: tool === 'bash' ? { command: 'python -m unittest' } : { filePath: 'example.py' } };
    await f.hooks['tool.execute.before']({ tool, sessionID: 'child', callID }, output);
    return output;
  }
  return { ...f, child, childMessages, use };
}

test('Build coder can inspect edit and test, with native approval arguments unchanged', async t => {
  const f = await coderFixture(t);
  for (const name of ['read', 'glob', 'grep', 'edit', 'write', 'apply_patch']) await f.use(name);
  assert.deepEqual((await f.use('bash')).args, { command: 'python -m unittest' });
  assert.equal(f.hooks['permission.ask'], undefined, 'policy must never auto-approve native requests');
  for (const name of ['task', 'webfetch', 'websearch', 'account_write']) {
    await assert.rejects(f.use(name), /not allowed/);
  }
});

test('native child return produces a complete source-bound review artifact', async t => {
  const f = await coderFixture(t);
  const raw = JSON.stringify({ summary: 'Reviewed', acceptance: [{ id: 'A1', status: 'met',
    evidence: 'Analysis complete', tool_call_ids: [] }], tests: [], changed_files: [], assumptions: [], unresolved: [] });
  f.childMessages.push({ info: { id: 'final', role: 'assistant', finish: 'stop' }, parts: [{ type: 'text', text: raw }] });
  const output = { output: 'Native wrapper', metadata: { sessionId: 'child' } };
  await f.hooks['tool.execute.after']({ tool: 'task', sessionID: 'session1', callID: 'delegate' }, output);
  const brief = JSON.parse(output.output), report = JSON.parse(await readFile(brief.full_report, 'utf8'));
  assert.equal(brief.status, 'ready_for_review');
  assert.equal(brief.full_report_required, false);
  assert.equal(brief.acceptance[0].evidence, 'Analysis complete');
  assert.equal(brief.acceptance[0].requirement, 'Task');
  assert.equal(report.raw_result, raw);
  assert.equal(report.acceptance[0].source.message_id, 'user1');
  assert.equal(report.acceptance[0].requirement, 'Task');
});

test('Plan coder can inspect but cannot mutate through edit write patch or shell', async t => {
  const f = await coderFixture(t, 'plan');
  for (const name of ['read', 'glob', 'grep']) await f.use(name);
  for (const name of ['edit', 'write', 'apply_patch', 'bash']) {
    await assert.rejects(f.use(name), /Plan coder is read-only/);
  }
});

test('coder requires active reserved parent task and cannot elevate another specialist', async t => {
  const f = await coderFixture(t);
  await assert.rejects(f.use('read', 'analyst'), /non-coder specialists/);
  f.messages.at(-1).parts[0].state.status = 'completed';
  await assert.rejects(f.use('edit'), /active coordinator task/);
  f.messages.at(-1).parts[0].state.status = 'running';
  f.messages.at(-1).parts[0].callID = 'unreserved';
  await assert.rejects(f.use('read'), /no reserved attempt/);
});

test('coder task has bounded native tool attempts and mode changes stop tools', async t => {
  const f = await coderFixture(t);
  for (let i = 0; i < 24; i++) await f.use('read');
  await assert.rejects(f.use('read'), /24-tool-attempt/);
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ instance_id: 'backend', epoch: 1, mode: 'normal' }) });
  await assert.rejects(f.use('bash'), /mode changed/);
});

test('direct coder uses explicit user turn with tools but cannot delegate', async t => {
  const f = await fixture(t);
  const call = f.call('direct');
  f.messages.at(-1).info.agent = 'coder';
  f.messages.at(-1).parts[0].tool = 'edit';
  call[0].tool = 'edit';
  await f.before(call);
  call[0].tool = 'task';
  await assert.rejects(f.before(call), /only the coordinator/);
  call[0].tool = 'webfetch';
  await assert.rejects(f.before(call), /not allowed/);
});

function mediaCall(f, id, kind = 'image') {
  const call = f.call(id);
  call[0].tool = 'local_' + kind;
  f.messages.at(-1).parts[0].tool = call[0].tool;
  return { call, context: { sessionID: 'session1', callID: id, ask: async () => {} } };
}

test('coordinator media asks approval, uses existing route and saves exact result', async t => {
  const f = await fixture(t), { context } = mediaCall(f, 'image1');
  let approved = false, posted;
  context.ask = async request => { assert.equal(request.permission, 'local_image'); approved = true; };
  globalThis.fetch = async (url, options) => {
    if (url.endsWith('/control/mode')) return { ok: true, json: async () => ({ instance_id: 'backend', epoch: 0, mode: 'normal' }) };
    assert(approved); posted = JSON.parse(options.body);
    return { ok: true, json: async () => ({ choices: [{ message: { content: '![Image](http://localhost/asset.png)' } }] }) };
  };
  const r = JSON.parse(await f.hooks.tool.local_image.execute({ prompt: 'A landscape' }, context));
  assert.equal(posted.messages[0].content, '/image A landscape');
  assert.equal(posted.media_mode_token, 'backend:0:normal');
  assert.equal(r.visually_verified, false);
  assert.equal(JSON.parse(await readFile(r.full_report)).prompt, 'A landscape');
  await assert.rejects(f.hooks.tool.local_image.execute({ prompt: 'Again' }, context), /duplicate media/);
});

test('media blocks specialist calls, invalid prompts, normal-mode video and denied approval', async t => {
  const f = await fixture(t), { context } = mediaCall(f, 'media1');
  await assert.rejects(f.hooks.tool.local_image.execute({ prompt: '' }, context), /prompt/);
  await assert.rejects(f.hooks.tool.local_video.execute({ prompt: 'Scene' }, context), /Max mode/);
  context.ask = async () => { throw Error('Denied'); };
  await assert.rejects(f.hooks.tool.local_image.execute({ prompt: 'Scene' }, context), /Denied/);
  f.messages.at(-1).info.agent = 'coder';
  await assert.rejects(f.hooks.tool.local_image.execute({ prompt: 'Scene' }, context), /only the coordinator/);
  f.session.parentID = 'parent';
  await assert.rejects(f.hooks.tool.local_image.execute({ prompt: 'Scene' }, context), /specialists/);
});

test('failed media is logged, counts against its own budget and is never auto-retried', async t => {
  const f = await fixture(t); let posts = 0;
  globalThis.fetch = async url => {
    if (url.endsWith('/control/mode')) return { ok: true, json: async () => ({ instance_id: 'backend', epoch: 0, mode: 'normal' }) };
    posts++; throw Error('Connection lost');
  };
  for (const id of ['one', 'two']) {
    const { context } = mediaCall(f, id);
    const r = JSON.parse(await f.hooks.tool.local_image.execute({ prompt: 'Scene' }, context));
    assert.equal(r.status, 'failed_or_unknown');
  }
  await assert.rejects(f.hooks.tool.local_image.execute({ prompt: 'Scene' }, mediaCall(f, 'three').context), /two media attempts/);
  assert.equal(posts, 2);
  const turn = Object.values(JSON.parse(await readFile(f.ledgerPath)).turns)[0];
  assert.equal(turn.calls.length, 0); assert.equal(turn.media.length, 2);
});

test('Max video works and media waits for an active specialist', async t => {
  const f = await fixture(t);
  let posted;
  globalThis.fetch = async (url, options) => url.endsWith('/control/mode')
    ? { ok: true, json: async () => ({ instance_id: 'backend', epoch: 0, mode: 'max' }) }
    : { ok: true, json: async () => { posted = JSON.parse(options.body); return { choices: [{ message: { content: '[Video](http://localhost/video.mp4)' } }] }; } };
  const hooks = await LocalTeam({ client: f.client, directory: f.directory }, { ...f.options, modeToken: 'backend:0:max' });
  const task = f.call('task'); await hooks['tool.execute.before'](...task);
  const { context } = mediaCall(f, 'video', 'video');
  await assert.rejects(hooks.tool.local_video.execute({ prompt: 'A wave' }, context), /active work/);
  await hooks['tool.execute.after'](task[0], { output: 'Result', metadata: {} });
  assert.equal(JSON.parse(await hooks.tool.local_video.execute({ prompt: 'A wave' }, context)).status, 'completed');
  assert.equal(posted.messages[0].content, '/video A wave');
});

test('mode changes during approval prevent media submission', async t => {
  const f = await fixture(t), { context } = mediaCall(f, 'one');
  context.ask = async () => {
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ instance_id: 'backend', epoch: 1, mode: 'normal' }) });
  };
  await assert.rejects(f.hooks.tool.local_image.execute({ prompt: 'Scene' }, context), /mode changed/);
  const turn = Object.values(JSON.parse(await readFile(f.ledgerPath)).turns)[0];
  assert.equal(turn.media, undefined);
});

test('coordinator speech supplies only exact text and registered voice options', async t => {
  const f = await fixture(t), { context } = mediaCall(f, 'speech');
  f.messages.at(-1).parts[0].tool = 'local_speech';
  let posted;
  context.ask = async r => assert.equal(r.permission, 'local_speech');
  globalThis.fetch = async (url, options) => url.endsWith('/control/mode')
    ? { ok: true, json: async () => ({ instance_id: 'backend', epoch: 0, mode: 'normal' }) }
    : { ok: true, json: async () => { posted = JSON.parse(options.body); return { choices: [{ message: { content: '[Speech](http://localhost/audio.wav)' } }] }; } };
  const result = JSON.parse(await f.hooks.tool.local_speech.execute({ prompt: 'Hello there', voice: 'default', language: 'English' }, context));
  assert.equal(posted.messages[0].content, '/speak Hello there');
  assert.deepEqual(posted.speech, { voice: 'default', language: 'English' });
  assert.equal(result.audibly_verified, false);
  await assert.rejects(f.hooks.tool.local_speech.execute({ prompt: 'Hello', voice: '../file', language: 'English' }, context), /registered voice/);
});

async function essayTurn(f,id='essay-user',draft='The result may improve by 10%.') {
  const message={info:{role:'user',id},parts:[{type:'text',text:'ESSAY_EDIT\n'+JSON.stringify({draft})}]};
  f.messages.push(message);await f.hooks['chat.message']({sessionID:'session1'},{message:message.info,parts:message.parts});
  const args=f.call('essay-call-'+id,'document',{},id);args[1].args.prompt='{}';return args;
}

test('essay delegation requires explicit current-turn activation and immutable supplied evidence',async t=>{
  const f=await fixture(t);const blocked=f.call('blocked','document');blocked[1].args.prompt='{}';
  await assert.rejects(f.before(blocked),/explicit ESSAY_EDIT/);
  const args=await essayTurn(f);
  const directive=f.messages.find(m=>m.info.id==='essay-user').parts.find(p=>p.synthetic);
  assert.match(directive.text,/Host document workflow/);
  assert.match(directive.text,/original, edited and notes paths/);
  assert(!directive.text.includes('Stage 7A'));
  const cross=f.call('cross-mode','scaffold_document',{},'essay-user');cross[1].args.prompt='{}';
  await assert.rejects(f.before(cross),/tool-free document specialist/);
  await f.before(args);
  const packet=JSON.parse(args[1].args.prompt);assert.equal(args[1].args.subagent_type,'essay_document');assert.equal(packet.essay_mode,'copyedit-v1');
  assert.equal(JSON.parse(packet.evidence).draft[0].text,'The result may improve by 10%.');
  assert.equal(JSON.parse(packet.constraints).reorder,'none');assert.ok(args[1].args.prompt.length<=12000);
  await f.after(args);
  const retry=f.call('essay-retry','document',{},'essay-user');retry[1].args.prompt=JSON.stringify({retry_failure:'Missing essay payload'});await f.before(retry);await f.after(retry);
  const third=f.call('essay-third','document',{},'essay-user');third[1].args.prompt='{}';await assert.rejects(f.before(third),/two specialist attempts/);
  const normal={info:{role:'user',id:'normal'},parts:[{type:'text',text:'Now explain regression.'}]};f.messages.push(normal);
  await f.hooks['chat.message']({sessionID:'session1'},{message:normal.info,parts:normal.parts});
  const next=f.call('unrelated','document',{},'normal');next[1].args.prompt='{}';await assert.rejects(f.before(next),/explicit ESSAY_EDIT/);
});
test('essay envelope limit preserves original and makes no specialist reservation',async t=>{
  const f=await fixture(t),draft='An unchanged paragraph. '.repeat(650);
  await assert.rejects(essayTurn(f,'long',draft),/does not fit/);
  const ledger=JSON.parse(await readFile(f.ledgerPath));const record=Object.values(ledger.turns).find(x=>x.essay);
  assert.equal(record.calls.length,0);assert.equal(record.essay.status,'incomplete_input_limit');
  assert.equal(await readFile(join(record.essay.folder,'essay.original.md'),'utf8'),draft);
});
test('native essay result is recovered, checked and saved separately with review status',async t=>{
  const f=await fixture(t),args=await essayTurn(f);await f.before(args);
  const native={summary:'Copyedited essay for author review.',acceptance:['A1','A2'].map(id=>({id,status:'met',evidence:'Model review only',tool_call_ids:[]})),changed_files:[],tests:[],assumptions:[],unresolved:[],essay:{paragraphs:[{id:'P1',text:'The result may improve by 10%.',removed_notes:[],beats:'A+C'}],editorial_notes:'Uncertain quotations: None identified. Unsupported claims: not verified. Meaning or structure concerns: None identified. Drafting notes and placeholders: None identified. Rhythm findings: no change warranted.',moves:[]}};
  const get=f.client.session.get,messages=f.client.session.messages;
  f.client.session.get=async a=>a.path.id==='essay-child'?{data:{parentID:'session1'}}:get(a);
  f.client.session.messages=async a=>a.path.id==='essay-child'?{data:[{info:{role:'assistant',finish:'stop'},parts:[{type:'text',text:JSON.stringify(native)}]}]}:messages(a);
  const output={output:'native clipped summary',metadata:{sessionId:'essay-child'}};
  await f.hooks['tool.execute.after'](args[0],output);const review=JSON.parse(output.output);
  assert.equal(review.status,'review_required');assert.equal(await readFile(review.essay.edited,'utf8'),'The result may improve by 10%.\n');
  assert.equal(await readFile(review.essay.original,'utf8'),'The result may improve by 10%.');
});

async function scaffoldTurn(f,id='scaffold-user'){
 const value={run_id:'test',stage:'1',brief_sufficient:true,word_count:240,referencing_style:'Harvard',sources:[{id:'B',kind:'brief',title:'Official brief',anchors:[{id:'B:AC1.1',kind:'criterion',text:'Explain distributions with examples.'}]}]};
 const m={info:{role:'user',id},parts:[{type:'text',text:'REVERSE_SCAFFOLD\n'+JSON.stringify(value)}]};f.messages.push(m);
 await f.hooks['chat.message']({sessionID:'session1'},{message:m.info,parts:m.parts});
 const args=f.call('scaffold-'+id,'document',{},id);args[1].args.prompt='{}';return args;
}
test('reverse scaffolding binds one stage and shares the two-attempt native budget',async t=>{
 const f=await fixture(t),args=await scaffoldTurn(f);await f.before(args);
 const directive=f.messages.find(m=>m.info.id==='scaffold-user').parts.find(p=>p.synthetic);
 assert.match(directive.text,/Stage 7A/);
 assert(!directive.text.includes('original, edited and notes paths'));
 const packet=JSON.parse(args[1].args.prompt),evidence=JSON.parse(packet.evidence);
 assert.equal(args[1].args.subagent_type,'scaffold_document');assert.equal(packet.scaffold_mode,'reverse-v1');assert.equal(packet.essay_mode,undefined);
 assert.equal(evidence.control.requested_stage,'1');assert.equal(evidence.control.attempt,1);
 await f.after(args);
 const retry=f.call('scaffold-retry','document',{},'scaffold-user');retry[1].args.prompt=JSON.stringify({retry_failure:'Missing structured stage result'});await f.before(retry);await f.after(retry);
 const third=f.call('scaffold-third','document',{},'scaffold-user');third[1].args.prompt=JSON.stringify({retry_failure:'Still invalid'});await assert.rejects(f.before(third),/two specialist attempts/);
 const wrong=f.call('scaffold-coder','coder',{},'scaffold-user');await assert.rejects(f.before(wrong),/tool-free document/);
});
test('native scaffold artifact is checked and never self-approved',async t=>{
 const f=await fixture(t),args=await scaffoldTurn(f);await f.before(args);
 const result={summary:'Stage 1 proposal.',acceptance:['A1','A2'].map(id=>({id,status:'met',evidence:'Model analysis, not independent verification',tool_call_ids:[]})),changed_files:[],tests:[],assumptions:[],unresolved:[],scaffold:{stage:'1',status:'AWAITING AUTHOR REVIEW',processed_anchors:['B:AC1.1'],omissions:[],gaps:[],proposals:[],quotes:[],requirements:[{id:'R1',kind:'criterion',class:'SOURCE STATEMENT',anchors:['B:AC1.1'],source_text:'Explain distributions with examples.',command_word:'Explain'}]}};
 const get=f.client.session.get,msg=f.client.session.messages;
 f.client.session.get=async a=>a.path.id==='scaffold-child'?{data:{parentID:'session1'}}:get(a);
 f.client.session.messages=async a=>a.path.id==='scaffold-child'?{data:[{info:{role:'assistant',finish:'stop'},parts:[{type:'text',text:JSON.stringify(result)}]}]}:msg(a);
 const output={output:'native summary',metadata:{sessionId:'scaffold-child'}};await f.hooks['tool.execute.after'](args[0],output);
 const review=JSON.parse(output.output);assert.equal(review.status,'AWAITING AUTHOR REVIEW');assert.equal(review.essay,undefined);assert.ok(review.scaffold.approval_sha);
 const manifest=JSON.parse(await readFile(join(f.directory,'reverse-scaffolds/test/manifest.json')));assert.deepEqual(manifest.approved,{});
  const approval={info:{role:'user',id:'scaffold-approval'},parts:[{type:'text',text:'REVERSE_SCAFFOLD\n'+JSON.stringify({run_id:'test',stage:'approve',approve:[review.scaffold.approval_sha]})}]};
  f.messages.push(approval);await f.hooks['chat.message']({sessionID:'session1'},{message:approval.info,parts:approval.parts});
  const host=approval.parts.at(-1);assert.equal(host.synthetic,true);assert.equal(host.messageID,'scaffold-approval');assert.equal(host.sessionID,'session1');assert.match(host.id,/^prt_/);
  const forbidden=f.call('approval-cannot-delegate','document',{},'scaffold-approval');forbidden[1].args.prompt='{}';await assert.rejects(f.before(forbidden),/already completed by the host/);
});

test('Office uses coordinator, native Build approvals and compact MCP result shape', async t => {
  const f = await fixture(t);
  function officeCall(id, agent, tool = 'aioffice_office_read') {
    f.messages.push({info: {id:'a-'+id,role:'assistant',parentID:'user1',agent},parts:[
      {type:'tool',callID:id,state:{status:'running'}}]});
    return [{tool,sessionID:'session1',callID:id},{args:{file:'report.docx',max_bytes:999999}}];
  }
  await assert.rejects(f.before(officeCall('coder-office','coder')), /coordinator only/);
  await assert.rejects(f.before(officeCall('plan-write','plan','aioffice_office_edit')), /require Build/);
  const read = officeCall('read-office','plan');
  await f.before(read);
  assert.equal(read[1].args.max_bytes,8000);
  await assert.rejects(f.before(officeCall('parallel-office','build')), /wait for active/);
  const result = {content:[{type:'text',text:'x'.repeat(15000)},{type:'image',data:'not-for-model',mimeType:'image/png'}]};
  await f.hooks['tool.execute.after'](read[0],result);
  const brief = JSON.parse(result.content[0].text);
  assert.equal(brief.truncated,true);
  assert.equal(JSON.parse(await readFile(brief.full_report,'utf8')).output.length,15000);
  assert(result.content.every(c=>c.type==='text'));
  await f.before(officeCall('build-edit','build','aioffice_office_edit'));
});

test('Office cannot bypass essay workflow restrictions', async t => {
  const f = await fixture(t);
  const id = 'essay-user';
  const user = {info:{id,role:'user'},parts:[{type:'text',text:'ESSAY_EDIT\n'+JSON.stringify({draft:'Original text.'})}]};
  f.messages.push(user);
  await f.hooks['chat.message']({sessionID:'session1'},{message:user.info,parts:user.parts});
  f.messages.push({info:{id:'essay-assistant',role:'assistant',parentID:id,agent:'build'},parts:[
    {type:'tool',callID:'essay-office',state:{status:'running'}}]});
  await assert.rejects(f.before([{tool:'aioffice_office_edit',sessionID:'session1',callID:'essay-office'},
    {args:{file:'essay.docx',ops:[]}}]), /separate request/);
});
