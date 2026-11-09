// OpenCode v1.18.34 policy hooks. Native task owns the child session/tool loop.
// No inference calls or account credentials. Contracts/reports contain local text.
import { readFile, open, rename } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import {workers as captainWorkers, activeCaptains} from './captain-runtime.mjs';
import { dirname, join, resolve } from 'node:path';
import { isDeepStrictEqual, promisify } from 'node:util';
import { execFile as execFileCallback } from 'node:child_process';
import { hash, validateContract, bindContract, assessResult, reviewBrief, saveArtifact, RESULT_INSTRUCTION, NATIVE_RESULT_INSTRUCTION, nativeResultFormat } from './handoff-contract.mjs';

import {parseRequest, preserve, loadRequest, makeContract, persistResult, RETURN_INSTRUCTION as ESSAY_RETURN} from './essay-edit.mjs';

import {parseScaffold, beginScaffold, loadScaffold, scaffoldContract, finishScaffold, SCAFFOLD_RETURN} from './reverse-scaffold.mjs';

const MAX_INPUT = 12000;
const CODER_TOOLS = new Set(['read', 'glob', 'grep', 'edit', 'write', 'apply_patch', 'bash']);
const READ_TOOLS = new Set(['read', 'glob', 'grep']);
const MAINTENANCE_AGENTS = new Set(['compaction', 'summary', 'title']);
const OFFICE_READ = new Set(['office_read', 'office_query', 'office_get', 'office_validate', 'office_help', 'office_status']);
const fields = ['objective', 'constraints', 'evidence', 'completed', 'remaining', 'result'];
const stores = new Map();
const turnKey = (session, message) => createHash('sha256').update(session + '\0' + message).digest('hex');
const fail = (text) => { throw new Error('Local model team: ' + text); };
const execFile = promisify(execFileCallback);
const operationError = response => {
  const error = response?.error;
  return typeof error === 'string' ? error : error?.data?.message ?? error?.message ?? JSON.stringify(error ?? 'missing data');
};
const data = (response, context = 'native session lookup') => {
  if (response.error || !response.data) fail('could not verify native session identity: ' + context
    + '; HTTP ' + (response.response?.status ?? 'unknown') + '; ' + operationError(response).slice(0, 512));
  return response.data;
};

function resumeState(messages, explicit, overflow) {
  const index = messages.findLastIndex(explicit);
  if (index < 0) return;
  const user = messages[index];
  const assistant = messages.slice(index + 1).findLast(message => message.info.role === 'assistant'
    && !message.info.summary && !MAINTENANCE_AGENTS.has(message.info.agent));
  const tools = assistant?.parts.filter(part => part.type === 'tool') ?? [];
  if (tools.some(part => ['pending', 'running'].includes(part.state?.status))) return;
  if (assistant?.info.error) return;
  if (assistant?.info.structured !== undefined) return;
  const unfinished = !assistant || ['tool-calls', 'length'].includes(assistant.info.finish)
    || (overflow && !assistant.info.finish);
  if (!unfinished) return;
  // A completed answer is terminal even when a synthetic user part asks for
  // more. A resume without subsequent assistant/tool progress gets no second go.
  return {user, assistantID: assistant?.info.id, unanswered: !assistant,
    checkpoint: hash(JSON.stringify([user.info.id, assistant?.info.id,
    assistant?.info.finish, tools.map(part => [part.callID, part.state?.status])]))};
}

async function loadStore(ledgerPath) {
  let ledger = JSON.parse(await readFile(ledgerPath, 'utf8'));
  if (ledger.version !== 1 || !ledger.turns || Array.isArray(ledger.turns)) fail('invalid budget ledger');
  let queue = Promise.resolve();
  // All reservations are serialized, persisted before execution and never refunded.
  const exclusive = (fn) => {
    const result = queue.then(fn);
    queue = result.catch(() => {});
    return result;
  };
  async function save() {
    const temporary = ledgerPath + '.tmp';
    const file = await open(temporary, 'w', 0o600);
    try { await file.writeFile(JSON.stringify(ledger)); await file.sync(); }
    finally { await file.close(); }
    await rename(temporary, ledgerPath);
    const directory = await open(dirname(ledgerPath), 'r');
    try { await directory.sync(); } finally { await directory.close(); }
  }
  // A crashed task still consumed its attempt. Never re-execute an old call ID.
  for (const turn of Object.values(ledger.turns)) {
    if (!Array.isArray(turn.calls) || turn.calls.length > 2) fail('invalid turn ledger');
    for (const call of turn.calls) if (call.status === 'reserved') call.status = 'interrupted';
    if (turn.media !== undefined && (!Array.isArray(turn.media) || turn.media.length > 2)) fail('invalid media ledger');
    for (const call of turn.media ?? []) if (call.status === 'reserved') call.status = 'interrupted';
    if (turn.office !== undefined && (!Array.isArray(turn.office) || turn.office.length > 24)) fail('invalid Office ledger');
    for (const call of turn.office ?? []) if (call.status === 'reserved') call.status = 'interrupted';
  }
  await save();
  return { ledger, exclusive, save, active: new Map() };
}

export default async function LocalTeam({ client, directory }, options = {}) {
  const { ledgerPath, roles, modeToken } = options;
  const nativeStructuredResults = options.nativeStructuredResults === true;
  const capabilities = options.capabilities ?? {media: true, speech: true};
  if (!ledgerPath || !directory || !roles?.coordinator || !roles?.analyst || !roles?.coder || !modeToken) fail('configuration missing');
  if (!stores.has(ledgerPath)) stores.set(ledgerPath, loadStore(ledgerPath));
  const { ledger, exclusive, save, active } = await stores.get(ledgerPath);
  const childResumeMarks = new Map();

  function explicitUser(session, sessionID, message) {
    return message.info.role === 'user' && (session.parentID
      ? message.parts.some(part => part.type === 'text' && !part.metadata?.compaction_continue)
        && !message.parts.some(part => part.type === 'compaction')
      : !!ledger.turns[turnKey(sessionID, message.info.id)]);
  }

  function originalRequest(message) {
    const text = message.parts.filter(part => part.type === 'text' && !part.synthetic && !part.ignored)
      .map(part => part.text).join('\n');
    // Native task prompts may be synthetic, but remain the child session's
    // original bound objective. Never select maintenance followups as sources.
    const request = text || (message.parts.filter(part => part.type === 'text'
      && !part.metadata?.compaction_continue && !part.ignored).map(part => part.text).join('\n'));
    if (!request.trim() || request.length > MAX_INPUT) {
      fail('pending request cannot be restored within the 12000-character resume bound; resume it explicitly');
    }
    return request;
  }

  async function pendingRequestAnchor(sessionID, messageID) {
    const session = data(await client.session.get({path: {id: sessionID}}));
    const messages = await nativeMessages(session, sessionID);
    const user = messages.findLast(message => explicitUser(session, sessionID, message));
    if (!user) return;
    const turn = ledger.turns[turnKey(sessionID, user.info.id)];
    const authority = session.parentID ? childResumeMarks.get(sessionID) : turn?.compaction_resume;
    if (!authority || authority.userID !== user.info.id || !authority.checkpoint
        || (!session.parentID && authority.checkpoint !== turn.compaction_checkpoint)) return;
    // Only the actual latest maintenance user message may carry this anchor.
    // Older summaries/followups cannot activate a stale pending request.
    const latestUser = messages.findLast(message => message.info.role === 'user');
    if (latestUser?.info.id !== messageID) return;
    const index = messages.findIndex(message => message.info.id === user.info.id);
    const latest = messages.slice(index + 1).findLast(message => message.info.role === 'assistant'
      && !message.info.summary && !MAINTENANCE_AGENTS.has(message.info.agent)
      && (message.info.finish || message.info.error || message.parts.length));
    if (latest?.info.error || latest?.info.structured !== undefined || latest?.info.finish === 'stop') return;
    const request = originalRequest(user);
    return 'Native session state: the original user request below remains '
      + (authority.unanswered ? 'unanswered' : 'unfinished') + '. '
      + 'A summary claiming it was completed is not evidence of a delivered answer. '
      + 'Answer or finish this original request now. This resumes existing work with its existing permissions and budgets. '
      + 'Do not merely announce that there is nothing to do.\nOriginal user request, verbatim:\n'
      + JSON.stringify(request);
  }

  async function coderBinding(sessionID, parentID, agent) {
    const callID = active.get(parentID);
    if (!callID) fail('structured coder input has no active parent handoff');
    const {key, messages} = await identity({sessionID: parentID, callID});
    const nativeTask = messages.flatMap(message => message.parts).find(part =>
      part.type === 'tool' && part.tool === 'task' && [part.callID, part.id].includes(callID));
    if (nativeTask?.state?.metadata?.sessionId !== sessionID || nativeTask.state.status !== 'running') {
      fail('structured coder input is not bound to the active native task child');
    }
    const call = ledger.turns[key].calls.find(item => item.id === callID);
    if (call?.role !== 'coder' || call.agent !== agent || call.status !== 'reserved') {
      fail('structured coder input does not match its reserved execution profile');
    }
    return {callID, call};
  }

  async function nativeMessages(session, sessionID) {
    if (session.id && session.id !== sessionID) fail('native session lookup returned a different identity');
    const response = await client.session.messages({path: {id: sessionID}});
    if (!response.error && response.data) return response.data;
    // v1.18.34 reloads format classes as plain JSON, then its history response
    // encoder rejects them. Only this exact codec failure may use the same
    // committed SQLite records through a read-only, parent-bound host reader.
    const reader = options.nativeHistoryReader;
    if (!nativeStructuredResults || !reader || !session.parentID ||
        !['coder', 'coder-plan'].includes(session.agent) || response.response?.status !== 400 ||
        !operationError(response).includes('Expected OutputFormatJsonSchema')) {
      return data(response, 'session.messages');
    }
    const {callID} = await coderBinding(sessionID, session.parentID, session.agent);
    const {stdout} = await execFile(reader.python, ['-I', reader.script,
      '--database', reader.database, '--session-id', sessionID, '--parent-id', session.parentID,
      '--call-id', callID, '--agent', session.agent, '--model-id', roles.coder],
      {timeout: 10000, maxBuffer: 8 * 1024 * 1024});
    const result = JSON.parse(stdout);
    if (result.source !== 'native_sqlite_readonly' || result.session_id !== sessionID ||
        result.parent_id !== session.parentID || !Array.isArray(result.messages)) {
      fail('native read-only history reader returned an invalid identity');
    }
    Object.defineProperty(result.messages, 'nativeHistorySource', {value: result.source});
    return result.messages;
  }

  async function checkMode() {
    const response = await fetch('http://127.0.0.1:8001/control/mode', {
      headers: { Authorization: 'Bearer ' + process.env.LOCAL_AI_GATEWAY_KEY },
      signal: AbortSignal.timeout(3000), redirect: 'error',
    });
    if (!response.ok) fail('gateway mode unavailable');
    const status = await response.json();
    if (status.transitioning || status.error || !['normal', 'max'].includes(status.mode)
        || `${status.instance_id}:${status.epoch}:${status.mode}` !== modeToken) {
      fail('gateway mode changed or restarted; restart the work agent');
    }
    return status;
  }

  function mediaTool(kind) {
    const name = kind === 'speak' ? 'local_speech' : 'local_' + kind;
    const limit = kind === 'speak' ? 2000 : 4000;
    return {
      description: kind === 'speak' ? 'Generate local Qwen3-TTS speech from the exact supplied wording using a registered voice. Normal or Max mode. Reference voices are configured locally, not uploaded through this tool. Returns a WAV link; cannot assess voice similarity.' : `Generate one ${kind} using the local media backend. ${kind === 'video' ? 'Requires Max mode; short silent clip.' : 'Normal or Max mode.'} Only for explicit user requests. Returns asset links, not a visual assessment.`,
      // v1.18.34 registry supports legacy JSON Schema args; validate again below.
      args: { prompt: { type: 'string', minLength: 1, maxLength: limit }, ...(kind === 'speak' ? {
        voice: { type: 'string', pattern: '^[a-z][a-z0-9_-]{0,39}$', description: 'Registered voice ID; use default unless a named voice was configured.' },
        language: { type: 'string', enum: ['auto', 'English', 'Chinese', 'Japanese', 'Korean', 'German', 'French', 'Russian', 'Portuguese', 'Spanish', 'Italian'] },
      } : {}) },
      async execute(args, context) {
        if (!args || Object.keys(args).some(k => !(kind === 'speak' ? ['prompt', 'voice', 'language'] : ['prompt']).includes(k)) || typeof args.prompt !== 'string' ||
            !args.prompt.trim() || args.prompt.length > limit) fail('media requires a prompt of 1–' + limit + ' characters');
        if (kind === 'speak' && ((args.voice !== undefined && (typeof args.voice !== 'string' || !/^[a-z][a-z0-9_-]{0,39}$/.test(args.voice))) ||
            (args.language !== undefined && !['auto', 'English', 'Chinese', 'Japanese', 'Korean', 'German', 'French', 'Russian', 'Portuguese', 'Spanish', 'Italian'].includes(args.language)))) fail('speech has an invalid registered voice ID or language');
        const input = { sessionID: context.sessionID, callID: context.callID };
        await identity(input);
        let status = await checkMode();
        if (kind === 'video' && status.mode !== 'max') fail('video requires Max mode; change modes and restart the work agent');
        await context.ask({ permission: name, patterns: ['*'], always: ['*'], metadata: { kind, ...args } });
        const started = new Date().toISOString();
        let record, key;
        await exclusive(async () => {
          await checkMode();
          ({ key } = await identity(input));
          const turn = ledger.turns[key];
          turn.media ??= [];
          if (turn.media.some(c => c.id === input.callID)) fail('duplicate media call; inspect its saved record');
          if (turn.media.length >= 2) fail('two media attempts already used for this user turn');
          if (active.has(input.sessionID)) fail('wait for active work before generating media');
          record = { id: input.callID, kind, ...args, started, status: 'reserved' };
          turn.media.push(record);
          await save();
          active.set(input.sessionID, input.callID);
        });
        let result;
        try {
          context.abort?.throwIfAborted();
          const response = await fetch('http://127.0.0.1:8001/v1/chat/completions', {
            method: 'POST', redirect: 'error',
            headers: { Authorization: 'Bearer ' + process.env.LOCAL_AI_GATEWAY_KEY, 'Content-Type': 'application/json' },
            signal: AbortSignal.any([AbortSignal.timeout(4200000), ...(context.abort ? [context.abort] : [])]),
            body: JSON.stringify({ model: roles.coordinator, stream: false, media_mode_token: modeToken,
              ...(kind === 'speak' ? { speech: {
                ...(args.voice === undefined ? {} : { voice: args.voice }),
                ...(args.language === undefined ? {} : { language: args.language }),
              } } : {}),
              messages: [{ role: 'user', content: '/' + kind + ' ' + args.prompt.trim() }] }),
          });
          const body = await response.json();
          if (!response.ok) throw new Error(body.error?.message ?? body.error ?? 'Media request failed');
          const content = body.choices?.[0]?.message?.content;
          if (typeof content !== 'string' || !content.trim()) throw new Error('Media response contained no asset links');
          result = { status: 'completed', output: content, ...(kind === 'speak' ? { audibly_verified: false } : { visually_verified: false }) };
        } catch (error) {
          result = { status: 'failed_or_unknown', error: String(error.message),
            instruction: 'Do not retry automatically. A disconnected or cancelled client does not prove the backend stopped. Check backend status and generated media first.' };
        }
        const finished = new Date().toISOString();
        const report = await saveArtifact(join(resolve(directory), '.local-ai-media'),
          hash(key + input.callID) + '.json', { ...record, ...result, finished,
            elapsed_seconds: (Date.parse(finished) - Date.parse(started)) / 1000 });
        await exclusive(async () => {
          Object.assign(record, { status: result.status, finished, report: report.path });
          await save();
          active.delete(input.sessionID);
        });
        return JSON.stringify({ ...result, full_report: report.path });
      },
    };
  }

  async function coderTool(input, session, messages, assistant) {
    if (assistant.info.agent === 'coder-plan' && !READ_TOOLS.has(input.tool)) fail('Plan coder is read-only');
    if (!CODER_TOOLS.has(input.tool)) fail('coder tool is not allowed');
    await checkMode();
    let relevant = messages;
    if (session.parentID) {
      const parent = data(await client.session.get({ path: { id: session.parentID } }));
      if (parent.parentID) fail('nested coder session');
      const history = data(await client.session.messages({ path: { id: session.parentID } }));
      const owner = history.find(m => m.info.role === 'assistant' && m.parts.some(p =>
        p.type === 'tool' && p.tool === 'task' && p.state?.metadata?.sessionId === input.sessionID));
      const task = owner?.parts.find(p => p.type === 'tool' && p.tool === 'task' &&
        p.state?.metadata?.sessionId === input.sessionID);
      if (!task || !['plan', 'build'].includes(owner.info.agent) || task.state.status !== 'running') {
        fail('coder is not bound to an active coordinator task');
      }
      const { key } = await identity({ sessionID: session.parentID, callID: task.callID ?? task.id });
      const reserved = ledger.turns[key].calls.some(c =>
        [task.callID, task.id].includes(c.id) && c.role === 'coder' && c.status === 'reserved');
      if (!reserved) fail('coder handoff has no reserved attempt');
      if (owner.info.agent === 'plan' && !READ_TOOLS.has(input.tool)) fail('Plan coder is read-only; use Build for edits and tests');
    } else {
      const position = messages.findIndex(m => m.info.id === assistant.info.parentID);
      const origin = messages.slice(0, position + 1).findLastIndex(m => m.info.role === 'user' &&
        ledger.turns[turnKey(input.sessionID, m.info.id)]);
      if (position < 0 || origin < 0) fail('coder needs an explicit user turn');
      relevant = messages.slice(origin);
    }
    const attempts = relevant.flatMap(m => m.parts).filter(p => p.type === 'tool').length;
    if (attempts > 24) fail('coder reached its 24-tool-attempt limit');
    // Native tool execution follows this hook and still asks for edit/bash
    // permissions. This hook never grants or bypasses an approval.
  }

  async function identity(input) {
    const session = data(await client.session.get({ path: { id: input.sessionID } }));
    if (session.parentID) fail('specialists cannot use tools or delegate');
    const messages = data(await client.session.messages({ path: { id: input.sessionID } }));
    const assistant = messages.find(m => m.info.role === 'assistant' && m.parts.some(p =>
      p.type === 'tool' && (p.callID === input.callID || p.id === input.callID)));
    if (!assistant) fail('task is not bound to a native assistant message');
    if (!['plan', 'build'].includes(assistant.info.agent)) fail('only the coordinator can delegate');
    const position = messages.findIndex(m => m.info.id === assistant.info.parentID);
    if (position < 0) fail('originating user message missing');
    // Only chat.message registers explicit user input. Native overflow replay
    // copies ordinary-looking user parts without that hook; it earns no budget.
    const origin = messages.slice(0, position + 1).findLast(m => m.info.role === 'user' &&
      ledger.turns[turnKey(input.sessionID, m.info.id)]);
    if (!origin) fail('no explicit user turn');
    const key = turnKey(input.sessionID, origin.info.id);
    const sourceMessages = messages.slice(0, position + 1).filter(m => m.info.role === 'user' &&
      ledger.turns[turnKey(input.sessionID, m.info.id)]);
    return { key, messages, sourceMessages };
  }

  function envelope(args) {
    if (!['analyst', 'coder', 'document', 'essay_document', 'scaffold_document'].includes(args.subagent_type)) fail('specialist must be analyst, coder or an explicitly authorised document edit');
    if (args.task_id || args.background || args.command) fail('resuming, commands and background delegation are disabled');
    if (typeof args.description !== 'string' || args.description.length > 160) fail('description exceeds 160 characters');
    if (typeof args.prompt !== 'string' || args.prompt.length > MAX_INPUT) fail('handoff exceeds 12000 characters');
    let value;
    try { value = JSON.parse(args.prompt); } catch { fail('prompt must be a JSON handoff envelope'); }
    if (!value || Array.isArray(value) || typeof value !== 'object') fail('invalid handoff envelope');
    if (Object.keys(value).some(k => ![...fields, 'retry_failure', 'facts', 'assumptions', 'unknowns', 'references', 'acceptance'].includes(k))) fail('unknown handoff field');
    for (const field of fields) {
      if (typeof value[field] !== 'string') fail('handoff requires string field: ' + field);
    }
    if (!value.objective.trim() || !value.result.trim()) fail('objective and result must be explicit');
    if (value.retry_failure !== undefined && (typeof value.retry_failure !== 'string' || !value.retry_failure.trim())) fail('retry needs a concrete failure');
    validateContract(value);
    // Native task resolves @file references before inference. Escaped JSON keeps
    // supplied evidence literal and prevents implicit file/agent attachments.
    args.prompt = JSON.stringify(value).replaceAll('@', '\\u0040');
    return value;
  }

  return {
    async 'experimental.chat.messages.transform'(input, output) {
      const marker = '[OpenCode maintenance; not a new user request]\n';
      const lastUser = output.messages.findLastIndex(message => message.info.role === 'user');
      for (let index = 0; index < output.messages.length; index++) {
        const message = output.messages[index];
        if (message.info.role !== 'user') continue;
        const maintenance = message.parts.some(part => part.type === 'text' && part.synthetic
          && part.metadata?.compaction_continue === true);
        const anchor = index === lastUser && maintenance && message.info.sessionID
          ? await pendingRequestAnchor(message.info.sessionID, message.info.id) : undefined;
        let changed = false;
        const parts = message.parts.map(part => {
          if (part.type !== 'text' || !part.synthetic || part.metadata?.compaction_continue !== true
              || (!anchor && part.text.startsWith(marker))) return part;
          changed = true;
          return {...part, text: marker + (anchor ?? part.text)};
        });
        // Replace objects in the outbound array; do not edit stored user parts.
        if (changed) output.messages[index] = {...message, parts};
      }
    },
    async 'experimental.session.compacting'(input, output) {
      output.context.push('Host maintenance: synthetic continuation messages were generated by OpenCode, '
        + 'not requested by the user. Preserve that distinction. Keep only genuine unfinished user work '
        + 'in Active and Next Move. Completed conversational answers have no next action. '
        + 'An assistant invitation to continue is not a user instruction. Summarise completed chatter briefly.');
      const session = data(await client.session.get({path: {id: input.sessionID}}));
      const messages = await nativeMessages(session, input.sessionID);
      const state = resumeState(messages, message => explicitUser(session, input.sessionID, message), true);
      if (state) output.context.push('Native history records the latest genuine user request as '
        + (state.unanswered ? 'unanswered: there is no ordinary assistant reply after it.' : 'unfinished: no terminal reply has been delivered.')
        + ' Do not mark requested output as already delivered. Request text is not completion evidence.');
    },
    async 'experimental.compaction.autocontinue'(input, output) {
      output.enabled = false;
      const session = data(await client.session.get({path: {id: input.sessionID}}));
      const messages = await nativeMessages(session, input.sessionID);
      // The persisted turn ledger records genuine root input through chat.message.
      // Native synthetic followups and overflow replays do not create new turns.
      const explicit = message => explicitUser(session, input.sessionID, message);
      const state = resumeState(messages, explicit, input.overflow === true);
      if (!state) return;
      originalRequest(state.user); // Do not authorise an unrecoverable resume.
      const authority = {checkpoint: state.checkpoint, userID: state.user.info.id,
        assistantID: state.assistantID, unanswered: state.unanswered};
      if (session.parentID) {
        if (childResumeMarks.get(input.sessionID)?.checkpoint === state.checkpoint) return;
        if (childResumeMarks.size >= 10000 && !childResumeMarks.has(input.sessionID)) return;
        childResumeMarks.set(input.sessionID, authority);
        output.enabled = true;
        return;
      }
      await exclusive(async () => {
        const turn = ledger.turns[turnKey(input.sessionID, state.user.info.id)];
        if (!turn || turn.compaction_checkpoint === state.checkpoint) return;
        turn.compaction_checkpoint = state.checkpoint;
        turn.compaction_resume = authority;
        await save();
        output.enabled = true;
      });
    },
    async 'chat.headers'(input, output) {
      const workflow = ({plan: 'captain', build: 'captain', analyst: 'analyst', coder: 'coder', 'coder-plan': 'coder',
        document: 'document', essay_document: 'essay', scaffold_document: 'scaffold',
        compaction: 'compaction', title: 'maintenance', summary: 'maintenance'})[input.agent]
        ?? (['researcher', 'analyst', 'coder', 'writer', 'reviewer'].some(role => input.agent === 'captain-' + role)
          ? 'worker.' + input.agent.slice('captain-'.length) : undefined);
      if (typeof workflow === 'string') output.headers['X-Local-AI-Workflow'] = workflow;
    },
    tool: { ...(capabilities.media ? {local_image: mediaTool('image'), local_video: mediaTool('video')} : {}),
            ...(capabilities.speech ? {local_speech: mediaTool('speak')} : {}) },
    async config(config) {
      // Base configuration denies task. Only successful plugin initialization
      // enables it, so a missing/broken policy file cannot allow unbounded work.
      config.tools.task = true;
      config.tools.local_image = !!capabilities.media;
      config.tools.local_video = !!capabilities.media && modeToken.endsWith(':max');
      config.tools.local_speech = !!capabilities.speech;
      for (const name of ['plan', 'build']) {
        config.agent[name].permission.task = { '*': 'deny', analyst: 'allow', coder: 'allow', 'coder-plan': 'allow', document: 'allow',
          essay_document: 'allow', scaffold_document: 'allow' };
        config.agent[name].permission.local_image = capabilities.media ? 'ask' : 'deny';
        config.agent[name].permission.local_video = capabilities.media && modeToken.endsWith(':max') ? 'ask' : 'deny';
        config.agent[name].permission.local_speech = capabilities.speech ? 'ask' : 'deny';
      }
    },
    async 'chat.message'(input, output) {
      const session = data(await client.session.get({ path: { id: input.sessionID } }));
      if (session.parentID) {
        if (output.parts.some(p => p.type !== 'text')) fail('specialist input must be supplied text only');
        const agent = input.agent ?? output.message?.agent;
        if (nativeStructuredResults && ['coder', 'coder-plan'].includes(agent)) {
          const {call} = await coderBinding(input.sessionID, session.parentID, agent);
          const saved = await readFile(call.contract_file, 'utf8');
          if (hash(saved) !== call.contract_sha256) fail('saved acceptance contract changed');
          // OpenCode persists this format before its native inference loop.
          // It supplies StructuredOutput alongside permitted inspection tools.
          output.message.format = nativeResultFormat(JSON.parse(saved), agent === 'coder-plan');
        }
        return;
      }
      if (!output.parts.some(p => !p.synthetic && ['text', 'file', 'agent'].includes(p.type))) return;
      if (typeof output.message?.id !== 'string') fail('explicit user message ID missing');
      await exclusive(async () => {
        const key = turnKey(input.sessionID, output.message.id);
        if (ledger.turns[key]) return;
        if (Object.keys(ledger.turns).length >= 10000) fail('ledger capacity reached; archive this work-agent state');
        const request = parseRequest(output.parts);
        const essay = request ? await preserve(directory, key, request) : undefined;
        const scaffoldRequest = parseScaffold(output.parts);
        const scaffold = scaffoldRequest ? await beginScaffold(dirname(ledgerPath), key, scaffoldRequest) : undefined;
        ledger.turns[key] = { calls: [], ...(essay ? {essay} : {}), ...(scaffold ? {scaffold} : {}) };
        if (scaffold?.result) output.parts.push({id:'prt_'+hash(key+'host-result').slice(0,28),messageID:output.message.id,sessionID:input.sessionID,type:'text',synthetic:true,text:'Host reverse-scaffold result (no specialist call): '+JSON.stringify(scaffold.result)});
        if ((essay || scaffold) && !scaffold?.result) output.parts.push({
          id: 'prt_' + hash(key + 'document-directive').slice(0, 28), messageID: output.message.id,
          sessionID: input.sessionID, type: 'text', synthetic: true,
          text: 'Host document workflow: call task with subagent_type document and prompt {}. '
            + 'The host supplies preserved sources, permissions and the active specialist profile. '
            + 'Do not edit or research independently, split the input or advance extra stages. '
            + 'One concrete failure permits a retry with {"retry_failure":"reason"}; preserve acceptance. '
            + (essay ? 'Return saved original, edited and notes paths with the actual review status. '
                + 'review_required needs author review; incomplete or needs_attention is unfinished.'
              : 'Process only the current scaffold stage. Return its artifact, status and approval hash. '
                + 'Stop at author review. Stage 7A plans research; source acquisition needs separate authorisation.')});
        await save();
        if (request) {
          const estimate = bindContract(makeContract(request), []);
          estimate.essay_mode = 'copyedit-v1';
          estimate.return_format = RESULT_INSTRUCTION + ESSAY_RETURN;
          if (JSON.stringify(estimate).replaceAll('@', '\\u0040').length > MAX_INPUT) {
            essay.status = 'incomplete_input_limit'; await save();
            fail('essay does not fit the 12000-character bound handoff. Original preserved; submit a separately scoped section.');
          }
        }
      });
    },
    async 'chat.params'(input) {
      const role = ['plan', 'build'].includes(input.agent) ? 'coordinator' : input.agent === 'coder-plan' ? 'coder' : input.agent;
      if (roles[role] && (input.model.providerID !== 'local-ai-gateway' || input.model.id !== roles[role])) {
        fail('agent model changed; use the configured role');
      }
    },
    async 'tool.execute.before'(input, output) {
      // The captain policy validates its host-registered native child sessions.
      if (captainWorkers.has(input.sessionID)) return;
      if (activeCaptains.has(input.sessionID) && !READ_TOOLS.has(input.tool) &&
          !['team_board', 'team_note', 'team_message', 'team_inbox', 'team_run'].includes(input.tool)) {
        fail('wait for the captain cohort before other effectful tools or specialist calls');
      }
      const session = data(await client.session.get({ path: { id: input.sessionID } }));
      if (input.tool.startsWith('aioffice_')) {
        await checkMode();
        const messages = data(await client.session.messages({ path: { id: input.sessionID } }));
        const assistant = messages.find(m => m.info.role === 'assistant' && m.parts.some(p =>
          p.type === 'tool' && (p.callID === input.callID || p.id === input.callID)));
        if (session.parentID || !['plan', 'build'].includes(assistant?.info.agent)) fail('Office tools belong to the coordinator only');
        const {key} = await identity(input);
        if (ledger.turns[key]?.essay || ledger.turns[key]?.scaffold) fail('Office operations require a separate request from essay/scaffold stages');
        const name = input.tool.slice('aioffice_'.length);
        if (assistant.info.agent === 'plan' && !OFFICE_READ.has(name)) fail('Office writes require Build and native approval');
        if (name === 'office_read') output.args.max_bytes = Math.min(Math.max(1, Number(output.args.max_bytes) || 8000), 8000);
        await exclusive(async () => {
          const turn = ledger.turns[key];
          turn.office ??= [];
          if (turn.office.some(c => c.id === input.callID)) fail('duplicate Office call; inspect its saved record');
          if (turn.office.length >= 24) fail('Office reached its 24-tool-attempt limit for this user turn');
          const last = active.get(input.sessionID);
          if (last) {
            const finished = messages.some(m => m.parts.some(p => p.type === 'tool' &&
              (p.callID === last || p.id === last) && ['error', 'completed'].includes(p.state?.status)));
            if (!finished) fail('wait for active work before Office operations');
            active.delete(input.sessionID);
          }
          turn.office.push({id: input.callID, tool: input.tool, status: 'reserved'});
          await save();
          active.set(input.sessionID, input.callID);
        });
      }
      if (session.parentID || input.tool !== 'task') {
        const messages = await nativeMessages(session, input.sessionID);
        const assistant = messages.find(m => m.info.role === 'assistant' && m.parts.some(p =>
          p.type === 'tool' && (p.callID === input.callID || p.id === input.callID)));
        if (['coder', 'coder-plan'].includes(assistant?.info.agent)) return coderTool(input, session, messages, assistant);
        if (session.parentID) fail('non-coder specialists cannot use tools or delegate');
        if (assistant && ['plan','build'].includes(assistant.info.agent) && input.tool !== 'task') {
          const {key} = await identity(input);
          if (ledger.turns[key]?.scaffold && input.tool !== 'read') fail('reverse-scaffold turns cannot execute tools except reading saved reports; source acquisition and editing require a separate explicit request');
        }
      }
      if (input.tool !== 'task') return;
      await exclusive(async () => {
        await checkMode();
        const { key, messages, sourceMessages } = await identity(input);
        const turn = ledger.turns[key] ?? { calls: [] };
        if (turn.calls.some(c => c.id === input.callID)) fail('duplicate call already consumed its attempt');
        if ((turn.essay || turn.scaffold) && !['document', turn.essay ? 'essay_document' : 'scaffold_document'].includes(output.args.subagent_type))
          fail('essay turns use the tool-free document specialist only');
        let essayRequest, scaffoldRequest;
        if (turn.scaffold?.result) fail('this scaffold step is already completed by the host; do not delegate or advance stages');
        if (['document', 'essay_document', 'scaffold_document'].includes(output.args.subagent_type)) {
          if (!roles.document || (!turn.essay && !turn.scaffold)) fail('document tasks require an explicit ESSAY_EDIT or REVERSE_SCAFFOLD request in this user turn');
          if (turn.essay) essayRequest = await loadRequest(turn.essay);
          if (turn.scaffold) scaffoldRequest = await loadScaffold(turn.scaffold);
          let supplied;
          try { supplied = JSON.parse(output.args.prompt); } catch { fail('document prompt must be JSON; use {} on the first attempt'); }
          if (!supplied || Array.isArray(supplied) || Object.keys(supplied).some(k => k !== 'retry_failure')) fail('document draft and permissions come only from the saved user request');
          output.args.prompt = JSON.stringify(essayRequest ? makeContract(essayRequest, supplied.retry_failure) : scaffoldContract(scaffoldRequest,turn.calls.length+1,supplied.retry_failure));
          output.args.subagent_type = essayRequest ? 'essay_document' : 'scaffold_document';
          if (output.args.prompt.length > MAX_INPUT) {
            (turn.essay || turn.scaffold).status = 'incomplete_input_limit'; await save();
            fail('essay does not fit the handoff; original preserved. Submit a separately scoped section, no silent truncation.');
          }
        }
        const value = envelope(output.args);
        const taskRole = ['essay_document', 'scaffold_document'].includes(output.args.subagent_type)
          ? 'document' : output.args.subagent_type;
        if (turn.calls.length >= 2) fail('two specialist attempts already used for this user turn');
        if (active.has(input.sessionID)) {
          // Errors do not call the after hook. Native persisted error state is
          // the only evidence that an outstanding operation has finished.
          const last = active.get(input.sessionID);
          const finished = messages.some(m => m.parts.some(p => p.type === 'tool' &&
            (p.callID === last || p.id === last) && ['error', 'completed'].includes(p.state?.status)));
          if (!finished) fail('wait for the active specialist before another handoff');
          active.delete(input.sessionID);
        }
        if (turn.calls.some(c => c.role === taskRole) && !value.retry_failure) {
          fail('a repeated specialist requires retry_failure describing the concrete failure');
        }
        const contract = bindContract(value, sourceMessages);
        const acceptanceHash = hash(JSON.stringify(contract.acceptance));
        const prior = turn.calls.find(c => c.role === taskRole);
        if (prior && prior.acceptance_hash !== acceptanceHash) fail('retry must preserve the original acceptance checklist');
        contract.return_format = nativeStructuredResults && taskRole === 'coder'
          ? NATIVE_RESULT_INSTRUCTION : RESULT_INSTRUCTION;
        if (essayRequest) {
          contract.essay_mode = 'copyedit-v1';
          contract.return_format += ESSAY_RETURN;
        }
        if (scaffoldRequest) {contract.scaffold_mode = 'reverse-v1';contract.return_format += SCAFFOLD_RETURN;}
        const packet = JSON.stringify(contract).replaceAll('@', '\\u0040');
        if (packet.length > MAX_INPUT) {
          if (essayRequest) {turn.essay.status = 'incomplete_input_limit'; await save();}
          fail('bound handoff exceeds 12000 characters; use a smaller explicitly scoped brief. The document agent cannot read file references.');
        }
        const saved = await saveArtifact(join(dirname(ledgerPath), 'handoff-contracts'),
          hash(key + input.callID) + '.json', contract);
        output.args.prompt = packet;
        // Resolve execution profile from the actual parent, never model-provided mode text.
        const owner = messages.find(m => m.info.role === 'assistant' && m.parts.some(p =>
          p.type === 'tool' && (p.callID === input.callID || p.id === input.callID)));
        if (taskRole === 'coder' && owner.info.agent === 'plan') output.args.subagent_type = 'coder-plan';
        turn.calls.push({ id: input.callID, role: taskRole, agent: output.args.subagent_type, status: 'reserved',
          acceptance_hash: acceptanceHash, contract_file: saved.path, contract_sha256: saved.sha256 });
        ledger.turns[key] = turn;
        await save();
        active.set(input.sessionID, input.callID);
      });
    },
    async 'tool.execute.after'(input, output) {
      if (captainWorkers.has(input.sessionID)) return;
      if (['read', 'glob', 'grep', 'bash'].includes(input.tool) &&
          typeof input.callID === 'string' && input.callID && typeof output.output === 'string') {
        output.output = 'Native tool evidence: ' + JSON.stringify({tool: input.tool, tool_call_id: input.callID})
          + '\n' + output.output;
      }
      if (input.tool.startsWith('aioffice_')) {
        const {key} = await identity(input);
        // Native MCP after hooks receive CallToolResult, unlike native tools'
        // {output,metadata}. The local team is text-only: do not inject images.
        const text = (output.content ?? []).filter(c => c.type === 'text').map(c => c.text).join('\n');
        const omitted = (output.content ?? []).filter(c => c.type !== 'text').map(c => c.type);
        const report = await saveArtifact(join(resolve(directory), '.local-ai-office'),
          hash(input.sessionID + input.callID) + '.json', {tool: input.tool, output: text, omitted_content_types: omitted});
        await exclusive(async () => {
          const record = ledger.turns[key].office?.find(c => c.id === input.callID);
          if (!record) fail('Office result has no reserved call');
          Object.assign(record, {status: 'completed', report: report.path});
          await save();
          if (active.get(input.sessionID) === input.callID) active.delete(input.sessionID);
        });
        output.content = [{type: 'text', text: text.length > 8000 ? JSON.stringify({truncated: true,
          excerpt: text.slice(0, 6000), full_report: report.path,
          instruction: 'This result is incomplete. Read a bounded section of the saved report or request a smaller document range. Do not treat the excerpt as complete evidence.'}) : text}];
        if (omitted.length) output.content.push({type: 'text', text: 'Binary preview omitted from this text-only model. Report saved file paths; visual appearance has not been checked.'});
        delete output.structuredContent;
        return;
      }
      if (input.tool !== 'task') return;
      const { key } = await identity(input);
      const call = ledger.turns[key].calls.find(c => c.id === input.callID);
      if (!call?.contract_file) fail('return has no saved acceptance contract');
      const text = await readFile(call.contract_file, 'utf8');
      if (hash(text) !== call.contract_sha256) fail('saved acceptance contract changed');
      const contract = JSON.parse(text);
      let raw = output.output;
      let nativeFinalText;
      let nativeFinalTextStatus;
      let nativeFormatCallID;
      let tools = [];
      const sourceIssues = [];
      const childID = output.metadata?.sessionId;
      if (!childID) sourceIssues.push('Native child session identity missing.');
      else {
        const child = data(await client.session.get({ path: { id: childID } }));
        if (child.parentID !== input.sessionID) fail('return belongs to another parent');
        const messages = await nativeMessages(child, childID);
        if (messages.nativeHistorySource) call.native_history_source = messages.nativeHistorySource;
        const final = messages.findLast(m => m.info.role === 'assistant');
        raw = final?.parts.filter(p => p.type === 'text').map(p => p.text).join('\n') ?? '';
        tools = messages.flatMap(m => m.parts).filter(p => p.type === 'tool');
        if (!final || final.info.error || final.info.finish === 'length') sourceIssues.push('Specialist response missing, failed or cut off.');
        if (nativeStructuredResults && call.role === 'coder') {
          nativeFinalText = raw;
          raw = ''; // Plain text cannot substitute for a native submission.
          nativeFinalTextStatus = nativeFinalText.trim() ? 'unverified_commentary' : 'empty';
          const structured = final?.info.structured;
          const submissions = (final?.parts ?? []).filter(p => p.type === 'tool' && p.tool === 'StructuredOutput');
          if (!structured || typeof structured !== 'object' || Array.isArray(structured)) {
            sourceIssues.push('Native structured final result missing.');
          } else {
            raw = JSON.stringify(structured);
            const submission = submissions[0];
            if (submissions.length !== 1 || submission.state?.status !== 'completed' ||
                typeof submission.callID !== 'string' || !submission.callID ||
                !isDeepStrictEqual(submission.state.input, structured)) {
              sourceIssues.push('Structured final result lacks its matching completed native submission.');
            } else nativeFormatCallID = submission.callID;
          }
          if (nativeFinalText.trim()) {
            // StructuredOutput is the native return channel. Keep accompanying
            // text for review; it supplies no result fields or execution evidence.
            // A second parseable JSON result must still agree with the submission.
            try {
              if (!isDeepStrictEqual(JSON.parse(nativeFinalText), structured)) {
                nativeFinalTextStatus = 'conflicting_json';
                sourceIssues.push('Final JSON text differs from native structured final result.');
              } else nativeFinalTextStatus = 'matching_result';
            } catch {
              nativeFinalTextStatus = 'unverified_commentary';
            }
          }
        }
      }
      const report = assessResult(contract, raw, tools, sourceIssues);
      if (call.native_history_source) report.native_history_source = call.native_history_source;
      if (nativeFinalText !== undefined) Object.assign(report, {
        result_transport: 'native_structured_output', native_final_text: nativeFinalText,
        native_final_text_status: nativeFinalTextStatus,
        ...(nativeFormatCallID ? {native_format_call_id: nativeFormatCallID} : {}),
      });
      if (call.role === 'document' && ledger.turns[key].essay) {
        const record = ledger.turns[key].essay;
        const request = await loadRequest(record);
        report.essay = await persistResult(record, input.callID, request, raw, report.issues.concat(
          report.acceptance.filter(c => c.status !== 'met').map(c => 'Unmet or unverified acceptance item: ' + c.id)));
        report.status = report.essay.status;
        report.issues.push(...report.essay.issues);
      }
      if (call.role === 'document' && ledger.turns[key].scaffold) {
        const record = ledger.turns[key].scaffold;
        report.scaffold = await exclusive(() => finishScaffold(record,input.callID,raw,report.issues.concat(
          report.acceptance.filter(c=>c.status!=='met').map(c=>'Unmet acceptance item: '+c.id)),ledger.turns[key].calls.indexOf(call)+1));
        report.status = report.scaffold.status;report.issues.push(...report.scaffold.issues);
      }
      const artifact = await saveArtifact(join(resolve(directory), '.local-ai-handoffs'),
        hash(key + input.callID + JSON.stringify(report)) + '.json', report);
      await exclusive(async () => {
        call.status = 'completed';
        call.review_status = report.status;
        call.result_sha256 = artifact.sha256;
        await save();
        active.delete(input.sessionID);
      });
      output.output = JSON.stringify({ ...reviewBrief(report),
        ...(report.essay ? {essay:report.essay} : {}), ...(report.scaffold ? {scaffold:report.scaffold} : {}),
        full_report: artifact.path, sha256: artifact.sha256,
        instruction: 'Review every criterion and its evidence. Read full_report when full_report_required is true or evidence is disputed or unclear. '
          + (report.native_final_text_status === 'unverified_commentary'
            ? 'Accompanying native_final_text is unverified commentary, not result or test evidence; review it for contradictions before relying on the handoff. ' : '')
          + 'Otherwise use this complete review brief without rereading the saved report. Unresolved items remain open. Native execution alone does not prove correctness.' });
      output.metadata = { ...output.metadata, localTeamReview: report.status, localTeamReport: artifact.path,
        localTeamReportSha256: artifact.sha256 };
    },
    async 'tool.definition'(input, output) {
      // OpenCode v1.18.34 marks every legacy `args` property required by
      // default. Speech has optional voice/language; only prompt is required.
      if (input.toolID === 'local_speech' && output.jsonSchema?.properties) {
        output.jsonSchema = { ...output.jsonSchema, required: ['prompt'] };
        return;
      }
      if (input.toolID !== 'task') return;
      output.description += '\nLocal team: at most two foreground attempts per user turn. Analyst or coder; document only for an explicit ESSAY_EDIT or REVERSE_SCAFFOLD user request. For document, prompt is {} or {retry_failure:concrete failure}; host supplies the preserved draft, permissions and contract. Do not construct or change its evidence. Other roles: '
        + 'prompt must be JSON with string fields objective, constraints, evidence, completed, remaining, result. '
        + 'Also require string lists facts, assumptions, unknowns; references:[{path:relative project path,symbol:string}]; '
        + 'acceptance:[{id:A1 through A8,requirement:string,source_quote:exact user quote or empty for derived criteria,'
        + 'verification:{kind:test|inspection|analysis,command:exact test command or empty}}]. '
        + 'A nonempty source_quote must equal requirement exactly and appear in an explicit user message. '
        + 'Retries must keep the same checklist. Specialist returns are checked against every ID and native tool records. '
        + 'Supply actual excerpts in evidence; paths are references only. Maximum 12000 characters. '
        + 'A repeated role requires retry_failure describing a concrete failure. No task_id, command or background.';
    },
  };
}
