// Boundary regression: real pinned SDK, HTTP, Effect codec, Python and SQLite.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp, rm, writeFile, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {execFile as callback} from 'node:child_process';
import {promisify} from 'node:util';
import LocalTeam from '../opencode-team.mjs';
import Captain from '../captain.mjs';
const execFile = promisify(callback);
const installer = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.LOCAL_AI_TEST_PYTHON ?? 'python';
const enabled = process.env.LOCAL_AI_EFFECT_ROOT && process.env.LOCAL_AI_OPENCODE_SDK_ROOT;

test('native child evidence survives the actual pinned history-codec rejection', {
  skip: !enabled && 'Set LOCAL_AI_EFFECT_ROOT and LOCAL_AI_OPENCODE_SDK_ROOT for the real boundary regression',
}, async t => {
  const effectRoot = resolve(process.env.LOCAL_AI_EFFECT_ROOT);
  const sdkRoot = resolve(process.env.LOCAL_AI_OPENCODE_SDK_ROOT);
  assert.equal(JSON.parse(await readFile(join(effectRoot, 'package.json'))).version, '4.0.0-beta.83');
  assert.equal(JSON.parse(await readFile(join(sdkRoot, 'package.json'))).version, '1.18.34');
  const {Effect, Schema} = await import(pathToFileURL(join(effectRoot, 'dist/index.js')).href);
  const {createOpencodeClient} = await import(pathToFileURL(join(sdkRoot, 'dist/client.js')).href);
  // Runtime format declaration used by the pinned native history endpoint.
  class OutputFormatJsonSchema extends Schema.Class('OutputFormatJsonSchema')({
    type: Schema.Literal('json_schema'), schema: Schema.Record(Schema.String, Schema.Any),
    retryCount: Schema.Int.check(Schema.isGreaterThanOrEqualTo(0)).pipe(
      Schema.optional, Schema.withDecodingDefault(Effect.succeed(2))),
  }) {}
  const History = Schema.Array(Schema.Struct({
    info: Schema.Struct({format: Schema.optional(OutputFormatJsonSchema)}), parts: Schema.Array(Schema.Any),
  }));
  for (const fault of [null, 'same-json', 'same-json-failed-read', 'same-json-forged-receipt',
    'conflicting-json', 'failed-read', 'forged-receipt', 'extra-prose',
    'prose-failed-read', 'prose-forged-receipt', 'prose-unrun-test', 'unauthorised', 'other-api-error']) {
    await t.test(String(fault), async t => {
      const root = await mkdtemp(join(tmpdir(), 'native-history-'));
      t.after(() => rm(root, {recursive: true, force: true}));
      const database = join(root, 'opencode.db');
      const reader = {python, script: join(installer, 'native_session_store.py'), database};
      async function seed(options) {
        await execFile(python, ['-I', '-c',
          'import sys,json;sys.path.insert(0,sys.argv[1]);from test_native_session_store import create_history;create_history(sys.argv[2],**json.loads(sys.argv[3]))',
          join(installer, 'tests'), database, JSON.stringify(options)]);
      }
      const messages = [{info: {id: 'user1', role: 'user', agent: 'plan', sessionID: 'session1'}, parts: [{type: 'text', text: 'Task'}]}];
      const child = {id: 'child', parentID: 'session1', agent: 'coder-plan'};
      let codecRejections = 0;
      const server = createServer(async (request, response) => {
        const url = new URL(request.url, 'http://localhost');
        const path = url.pathname;
        const limit = Number(url.searchParams.get('limit'));
        response.setHeader('Content-Type', 'application/json');
        try {
          if (path === '/session/session1') response.end(JSON.stringify({id: 'session1'}));
          else if (path === '/session/child') response.end(JSON.stringify(child));
          else if (path === '/session/session1/message') response.end(JSON.stringify(limit ? messages.slice(-limit) : messages));
          else if (path === '/session/child/message') {
            const {stdout} = await execFile(python, ['-I', reader.script, '--database', database,
              '--session-id', 'child', '--parent-id', 'session1', '--call-id', 'delegate',
              '--agent', 'coder-plan', '--model-id', 'code']);
            const saved = JSON.parse(stdout).messages;
            const history = limit ? saved.slice(-limit) : saved;
            try {
              Schema.encodeUnknownSync(History)(history);
              assert.equal(limit, 1, 'Only the bounded latest-assistant lookup avoids the saved format');
              response.end(JSON.stringify(history));
            }
            catch (error) {
              assert.match(error.message, /Expected OutputFormatJsonSchema/);
              codecRejections++;
              response.statusCode = fault === 'unauthorised' ? 401 : 400;
              response.end(JSON.stringify({name: 'BadRequest', data: {kind: 'Body',
                message: fault === 'other-api-error' ? 'Different API failure' : error.message}}));
            }
          } else {response.statusCode = 404; response.end('{}');}
        } catch (error) {response.statusCode = 500; response.end(JSON.stringify({message: error.message}));}
      });
      await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
      t.after(() => new Promise(resolve => server.close(resolve)));
      const client = createOpencodeClient({baseUrl: 'http://127.0.0.1:' + server.address().port});
      const previous = globalThis.fetch;
      globalThis.fetch = (input, options) => String(input?.url ?? input).endsWith('/control/mode')
        ? Promise.resolve(new Response(JSON.stringify({instance_id: 'backend', epoch: 0, mode: 'normal'})))
        : previous(input, options);
      t.after(() => {globalThis.fetch = previous;});
      const ledgerPath = join(root, 'budget.json');
      await writeFile(ledgerPath, JSON.stringify({version: 1, turns: {}}));
      const hooks = await LocalTeam({client, directory: root}, {ledgerPath,
        roles: {coordinator: 'coord', analyst: 'analysis', coder: 'code'}, modeToken: 'backend:0:normal',
        nativeStructuredResults: true, nativeHistoryReader: reader});
      const captain = await Captain({client, directory: root}, {statePath: join(root, 'captain.json'),
        modeToken: 'backend:0:normal', model: 'local-ai-gateway/coord', workspaceEnabled: false});
      // The pinned native loader invokes both policy plugins in this order.
      const trigger = async (name, input, output) => {
        for (const policy of [hooks, captain]) if (policy[name]) await policy[name](input, output);
      };
      await trigger('chat.message', {sessionID: 'session1'}, {message: messages[0].info, parts: messages[0].parts});
      const nativeReminder = await readFile(join(installer, 'tests/fixtures/opencode-1.18.34-plan.txt'), 'utf8');
      const prompt = {messages: structuredClone(messages)};
      prompt.messages[0].parts.push({type: 'text', text: nativeReminder, synthetic: true});
      await trigger('experimental.chat.messages.transform', {}, prompt);
      assert.match(prompt.messages[0].parts.at(-1).text, /Local AI Captain: read-only work/);
      assert.equal(messages[0].parts.length, 1, 'Only the inference copy changes');
      const task = {type: 'tool', tool: 'task', callID: 'delegate', state: {status: 'running'}};
      messages.push({info: {id: 'parent-assistant', parentID: 'user1', role: 'assistant', agent: 'plan'}, parts: [task]});
      const arguments_ = {args: {subagent_type: 'coder', description: 'Inspect arithmetic', prompt: JSON.stringify({
        objective: 'Read the supplied arithmetic.', constraints: 'Read only.', evidence: 'coder-acceptance.txt',
        completed: '', remaining: 'Task', result: 'Explain the arithmetic.', facts: [], assumptions: [], unknowns: [],
        references: [], acceptance: [{id: 'A1', requirement: 'Task', source_quote: 'Task', verification: {kind: 'inspection', command: ''}}],
      })}};
      await trigger('tool.execute.before', {tool: 'task', sessionID: 'session1', callID: 'delegate'}, arguments_);
      task.state.metadata = {sessionId: 'child'};
      const childInput = {message: {agent: 'coder-plan'}, parts: [{type: 'text', text: arguments_.args.prompt}]};
      await trigger('chat.message', {sessionID: 'child', agent: 'coder-plan'}, childInput);
      const nativeFormat = JSON.parse(JSON.stringify(childInput.message.format));
      await seed({native_format: nativeFormat});
      const inspection = trigger('tool.execute.before', {tool: 'read', sessionID: 'child', callID: 'read-real'},
        {args: {filePath: 'coder-acceptance.txt'}});
      if (['unauthorised', 'other-api-error'].includes(fault)) {
        await assert.rejects(inspection, fault === 'unauthorised' ? /HTTP 401/ : /Different API failure/);
        assert.equal(codecRejections, 1);
        return;
      }
      await inspection;
      await seed({native_format: nativeFormat, final: true,
        read_status: ['failed-read', 'same-json-failed-read', 'prose-failed-read'].includes(fault) ? 'error' : 'completed',
        claimed_id: ['forged-receipt', 'same-json-forged-receipt', 'prose-forged-receipt'].includes(fault) ? 'invented' : 'read-real',
        test_claim: fault === 'prose-unrun-test',
        final_text: fault?.startsWith('same-json') ? 'same-json' :
          fault === 'conflicting-json' ? 'conflicting-json' :
          fault === 'extra-prose' || fault?.startsWith('prose-') ? 'An unsupported extra claim.' : ''});
      const output = {output: 'Native task wrapper', metadata: {sessionId: 'child'}};
      await trigger('tool.execute.after', {tool: 'task', sessionID: 'session1', callID: 'delegate'}, output);
      const brief = JSON.parse(output.output), report = JSON.parse(await readFile(brief.full_report));
      const valid = !fault || ['same-json', 'extra-prose'].includes(fault);
      assert.equal(brief.status, valid ? 'ready_for_review' : 'needs_attention');
      assert.equal(report.native_history_source, 'native_sqlite_readonly');
      assert.equal(report.observed_tools.find(p => p.id === 'read-real').status,
        ['failed-read', 'same-json-failed-read', 'prose-failed-read'].includes(fault) ? 'error' : 'completed');
      assert.equal(codecRejections, 2);
      if (valid) assert.equal(report.acceptance[0].basis, 'native_inspection_recorded');
      if (fault === 'extra-prose' || fault?.startsWith('prose-')) {
        assert.equal(report.native_final_text_status, 'unverified_commentary');
        assert.equal(brief.full_report_required, true);
        assert(brief.report_read_reasons.includes('native_commentary_unverified'));
      }
    });
  }
});
