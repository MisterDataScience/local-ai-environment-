import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm, readFile, symlink, readdir, writeFile, mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import Captain, {validateTasks} from '../captain.mjs';
import {workers} from '../captain-runtime.mjs';

const task = (id, role = 'analyst') => ({id, role, objective: 'Investigate ' + id,
  constraints: 'Use supplied evidence; no unrelated work.', evidence: 'Source evidence for ' + id,
  deliverable: 'A bounded source-backed finding.'});

async function fixture(t, options = {}) {
  const root = await mkdtemp(join(tmpdir(), 'captain-'));
  const previous = globalThis.fetch;
  let status = {instance_id: 'gateway', epoch: 0, mode: 'max'};
  globalThis.fetch = async (url) => ({ok: true, json: async () => url.endsWith('/control/mode') ? status : {sources: [{url: 'https://example.org', text: 'Public evidence'}]}});
  t.after(async () => {globalThis.fetch = previous; for (const [id, b] of workers) if (b.parentID === root) workers.delete(id); await rm(root, {recursive: true, force: true});});
  const sessions = new Map([[root, {id: root}]]);
  const messages = new Map([[root, [{info: {id: 'user', role: 'user'}, parts: [{type: 'text', text: 'Research the supplied question.'}]}]]]);
  let count = 0, running = 0, maximum = 0;
  const aborted = [], deleted = [];
  const client = {session: {
    get: async ({path}) => ({data: sessions.get(path.id)}),
    messages: async ({path}) => ({data: messages.get(path.id) ?? []}),
    create: async ({body}) => {const id = root + '/worker' + (++count); sessions.set(id, {id, ...body}); return {data: {id}};},
    prompt: async ({path, body}) => {
      const assignment = JSON.parse(body.parts[0].text);
      messages.set(path.id, [{info: {id: 'child-user', role: 'user'}, parts: body.parts}]);
      running++; maximum = Math.max(maximum, running);
      try {await options.run?.({path, body, assignment, sessions, messages, hooks});}
      finally {running--;}
      const response = {info: {role: 'assistant', agent: body.agent, finish: 'stop'},
        parts: [{type: 'text', text: 'Finding for ' + assignment.task_id}]};
      messages.get(path.id).push(response); return {data: response};
    },
    abort: async ({path}) => {aborted.push(path.id); return {data: true};},
    delete: async ({path}) => {deleted.push(path.id); return {data: true};},
  }};
  const statePath = join(root, 'captain.json');
  const villageOptions = await options.village?.(root) ?? {};
  const hooks = await Captain({client, directory: root}, {statePath, modeToken: 'gateway:0:max',
    model: 'local-ai-gateway/local-ai-captain', maxWorkers: 5, maxTasks: options.maxTasks ?? 12,
    webEnabled: true, ...villageOptions});
  await hooks['chat.message']({sessionID: root}, {message: {id: 'user'}, parts: messages.get(root)[0].parts});
  function context(callID, agent = 'build', parentID = 'user') {
    messages.get(root).push({info: {id: 'assistant-' + callID, role: 'assistant', agent, parentID},
      parts: [{id: 'part-' + callID, callID, type: 'tool', tool: 'team_run', state: {status: 'running'}}]});
    return {sessionID: root, callID, abort: new AbortController().signal};
  }
  function workerContext(id, tool) {
    const b = workers.get(id), callID = 'call-' + tool + '-' + messages.get(id).length;
    messages.get(id).push({info: {role: 'assistant', agent: 'captain-' + b.task.role},
      parts: [{type: 'tool', tool, callID, state: {status: 'running'}}]});
    return {sessionID: id, callID, tool};
  }
  return {root, hooks, context, workerContext, messages, sessions, client, statePath, aborted, deleted,
    status: value => {status = value;}, maximum: () => maximum};
}

test('native workers overlap, retain source packets, publish messages and preserve reports on retirement', async t => {
  let release;
  const gate = new Promise(r => {release = r;});
  let arrivals = 0;
  const f = await fixture(t, {run: async ({path, assignment, hooks}) => {
    const context = f.workerContext(path.id, 'team_note');
    await hooks['tool.execute.before'](context);
    await hooks.tool.team_note.execute({text: 'Evidence from ' + assignment.task_id}, context);
    if (++arrivals === 3) release();
    await gate;
    const inbox = JSON.parse(await hooks.tool.team_inbox.execute({}, f.workerContext(path.id, 'team_inbox')));
    assert(inbox.length >= 1);
  }});
  const result = JSON.parse(await f.hooks.tool.team_run.execute({tasks: [task('mechanics'), task('matchups'), task('review', 'reviewer')]}, f.context('run')));
  assert.equal(f.maximum(), 3);
  assert(result.tasks.every(t => t.status === 'completed'));
  for (const item of result.tasks) {
    const report = JSON.parse(await readFile(item.report));
    assert.equal(report.task.evidence, 'Source evidence for ' + item.id);
    assert(report.native_tools.length);
  }
  await f.hooks.tool.team_retire.execute({ids: result.tasks.map(t => t.id)}, f.context('retire'));
  assert.equal(f.deleted.length, 3);
  assert(JSON.parse(await readFile(result.tasks[0].report)).output);
});

test('duplicate work, invalid profiles, excess workers and overlapping writers fail before dispatch', () => {
  assert.throws(() => validateTasks([task('a'), {...task('b'), objective: 'Investigate a'}]), /duplicate objective/);
  assert.throws(() => validateTasks([task('a', 'coder'), task('b', 'coder')]), /one editing/);
  assert.throws(() => validateTasks([task('a', 'admin')]), /invalid role/);
  assert.throws(() => validateTasks(Array.from({length: 6}, (_, i) => task('t' + i))), /submit 1/);
});

test('Village selects an active R daughter, falls back for C, and freezes the identity packet', async t => {
  const f = await fixture(t, {
    village: async root => {
      const villageRoot = join(root, 'village');
      await mkdir(villageRoot);
      await writeFile(join(villageRoot, 'village.sqlite'), '');
      const script = join(root, 'mock-village.cjs');
      await writeFile(script, `const [, , , , command, identity, value] = process.argv;
const result = command === 'host-route' ? (value.includes(' R ') ? 'coder.r' : 'coder.general')
  : command === 'host-packet' ? {id: identity, role: 'coder', revision: 1,
    instruction: identity === 'coder.r' ? 'Use R expertise.' : '', lessons: [],
    allowed_collections: ['general']} : [];
process.stdout.write(JSON.stringify(result));`);
      return {villageRoot, villagePython: process.execPath, villageScript: script};
    },
    run: async ({assignment}) => {
      if (assignment.task_id === 'r') {
        assert.equal(assignment.specialist.id, 'coder.r');
        assert.equal(assignment.specialist.revision, 1);
      } else assert.equal(assignment.specialist.id, 'coder.general');
    }
  });
  const tasks = [{...task('r', 'coder'), objective: 'Fix an R function'}];
  const first = JSON.parse(await f.hooks.tool.team_run.execute({tasks}, f.context('r')));
  assert.equal(first.tasks[0].status, 'completed');
  const second = JSON.parse(await f.hooks.tool.team_run.execute({tasks: [{...task('c', 'coder'), objective: 'Fix a C function'}]}, f.context('c')));
  assert.equal(second.tasks[0].status, 'completed');
});

test('attempt budgets and replay IDs survive errors and a fresh plugin instance', async t => {
  const f = await fixture(t, {maxTasks: 2, run: async () => {throw Error('concrete worker failure');}});
  const first = f.context('one');
  const result = JSON.parse(await f.hooks.tool.team_run.execute({tasks: [task('a')]}, first));
  assert.equal(result.tasks[0].status, 'failed');
  await assert.rejects(f.hooks.tool.team_run.execute({tasks: [task('b')]}, first), /duplicate dispatch/);
  await f.hooks.tool.team_run.execute({tasks: [task('b')]}, f.context('two'));
  await assert.rejects(f.hooks.tool.team_run.execute({tasks: [task('c')]}, f.context('three')), /budget/);
  const nativeHistory = f.messages.get(f.root);
  nativeHistory.push({info: {id: 'synthetic-user', role: 'user'}, parts: [{type: 'text', synthetic: true, text: 'Continue'}]});
  await f.hooks['chat.message']({sessionID: f.root}, {message: {id: 'synthetic-user'}, parts: nativeHistory.at(-1).parts});
  await assert.rejects(f.hooks.tool.team_run.execute({tasks: [task('d')]}, f.context('four', 'build', 'synthetic-user')), /budget/);
  const ledger = JSON.parse(await readFile(f.statePath));
  assert.equal(Object.keys(ledger.turns).length, 1);
  assert.equal(Object.values(ledger.turns)[0].tasks.length, 2);
});

test('Plan children cannot edit; Build coder tools retain native approval enforcement', async t => {
  const f = await fixture(t, {run: async ({path, sessions, hooks}) => {
    const c = f.workerContext(path.id, 'edit');
    await assert.rejects(hooks['tool.execute.before'](c), /outside/);
    assert(sessions.get(path.id).permission.some(p => p.permission === 'edit' && p.action === 'deny'));
  }});
  await f.hooks.tool.team_run.execute({tasks: [task('proposal', 'coder')]}, f.context('plan', 'plan'));
  const g = await fixture(t, {run: async ({path, sessions, hooks}) => {
    const c = g.workerContext(path.id, 'edit');
    await hooks['tool.execute.before'](c);
    assert(!sessions.get(path.id).permission.some(p => p.permission === 'edit' && p.action === 'allow'));
    const forbidden = g.workerContext(path.id, 'team_run');
    await assert.rejects(hooks['tool.execute.before'](forbidden), /outside/);
  }});
  await g.hooks.tool.team_run.execute({tasks: [task('implementation', 'coder')]}, g.context('build'));
});

test('mode changes invalidate workers and prevent follow-on tools', async t => {
  const f = await fixture(t, {run: async ({path, hooks}) => {
    f.status({instance_id: 'gateway', epoch: 1, mode: 'gaming'});
    await assert.rejects(hooks['tool.execute.before'](f.workerContext(path.id, 'read')), /mode changed/);
  }});
  const result = JSON.parse(await f.hooks.tool.team_run.execute({tasks: [task('audit')]}, f.context('run')));
  assert.equal(result.tasks[0].status, 'failed');
  assert.equal(f.aborted.length, 1);
});

test('only researchers use the existing VPN bridge; web failures never fall back', async t => {
  const f = await fixture(t, {run: async ({path, hooks}) => {
    const c = f.workerContext(path.id, 'team_search');
    await hooks['tool.execute.before'](c);
    assert(JSON.parse(await hooks.tool.team_search.execute({query: 'public game patch notes'}, c)).sources.length);
    const message = f.workerContext(path.id, 'team_message');
    await assert.rejects(hooks.tool.team_message.execute({to: 'unknown-session', text: 'hello'}, message), /unknown peer/);
  }});
  await f.hooks.tool.team_run.execute({tasks: [task('patch', 'researcher')]}, f.context('research'));
});

test('unknown child identities and explicit essay workflows cannot dispatch a team', async t => {
  const f = await fixture(t);
  f.messages.get(f.root).push({info: {id: 'essay-user', role: 'user'}, parts: [{type: 'text', text: 'ESSAY_EDIT input'}]});
  await f.hooks['chat.message']({sessionID: f.root}, {message: {id: 'essay-user'}, parts: f.messages.get(f.root).at(-1).parts});
  await assert.rejects(f.hooks.tool.team_run.execute({tasks: [task('a')]}, f.context('essay', 'build', 'essay-user')), /existing contracts/);
  f.sessions.set('unknown', {id: 'unknown', parentID: f.root});
  await assert.rejects(f.hooks.tool.team_board.execute({}, {sessionID: 'unknown', callID: 'forged'}), /unregistered/);
});

test('report directory cannot redirect task evidence outside the project', async t => {
  const f = await fixture(t);
  const outside = await mkdtemp(join(tmpdir(), 'captain-outside-'));
  t.after(() => rm(outside, {recursive: true, force: true}));
  await symlink(outside, join(f.root, '.local-ai-team'), 'dir');
  const result = JSON.parse(await f.hooks.tool.team_run.execute({tasks: [task('audit')]}, f.context('report')));
  assert.equal(result.tasks[0].status, 'failed');
  assert.match(result.tasks[0].error, /report directory/);
  assert.deepEqual(await readdir(outside), []);
});

test('parent cancellation fences workers even if a native prompt returns late', async t => {
  const controller = new AbortController();
  const f = await fixture(t, {run: async ({path, hooks}) => {
    controller.abort();
    await assert.rejects(hooks['tool.execute.before'](f.workerContext(path.id, 'read')), /no longer active/);
  }});
  const context = {...f.context('cancel'), abort: controller.signal};
  const result = JSON.parse(await f.hooks.tool.team_run.execute({tasks: [task('audit')]}, context));
  assert.equal(result.tasks[0].status, 'cancelled');
  assert(f.aborted.length >= 1);
});

test('host enforces twelve worker inference attempts and a fixed native identity', async t => {
  const f = await fixture(t, {run: async ({path, hooks}) => {
    const input = {sessionID: path.id, agent: 'captain-analyst',
      model: {providerID: 'local-ai-gateway', id: 'local-ai-captain'}};
    await assert.rejects(hooks['chat.params']({...input, agent: 'captain-coder'}), /identity changed/);
    for (let i = 0; i < 12; i++) await hooks['chat.params'](input);
    await assert.rejects(hooks['chat.params'](input), /inference-step budget/);
  }});
  const result = JSON.parse(await f.hooks.tool.team_run.execute({tasks: [task('budget')]}, f.context('steps')));
  assert.equal(result.tasks[0].status, 'completed');
  const ledger = JSON.parse(await readFile(f.statePath));
  assert.equal(Object.values(ledger.turns)[0].tasks[0].modelSteps, 12);
});
