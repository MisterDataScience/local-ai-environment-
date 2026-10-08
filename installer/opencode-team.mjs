// OpenCode v1.18.34 policy hooks. Native task owns the child session/tool loop.
// No inference calls or account credentials. Contracts/reports contain local text.
import { readFile, open, rename } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { hash, validateContract, bindContract, assessResult, saveArtifact, RESULT_INSTRUCTION } from './handoff-contract.mjs';

import {parseRequest, preserve, loadRequest, makeContract, persistResult, RETURN_INSTRUCTION as ESSAY_RETURN} from './essay-edit.mjs';

const MAX_INPUT = 12000;
const CODER_TOOLS = new Set(['read', 'glob', 'grep', 'edit', 'write', 'apply_patch', 'bash']);
const READ_TOOLS = new Set(['read', 'glob', 'grep']);
const fields = ['objective', 'constraints', 'evidence', 'completed', 'remaining', 'result'];
const stores = new Map();
const turnKey = (session, message) => createHash('sha256').update(session + '\0' + message).digest('hex');
const fail = (text) => { throw new Error('Local model team: ' + text); };
const data = (response) => {
  if (response.error || !response.data) fail('could not verify native session identity');
  return response.data;
};

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
  }
  await save();
  return { ledger, exclusive, save, active: new Map() };
}

export default async function LocalTeam({ client, directory }, options = {}) {
  const { ledgerPath, roles, modeToken } = options;
  if (!ledgerPath || !directory || !roles?.coordinator || !roles?.analyst || !roles?.coder || !modeToken) fail('configuration missing');
  if (!stores.has(ledgerPath)) stores.set(ledgerPath, loadStore(ledgerPath));
  const { ledger, exclusive, save, active } = await stores.get(ledgerPath);

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
        if (kind === 'speak' && (typeof args.voice !== 'string' || !/^[a-z][a-z0-9_-]{0,39}$/.test(args.voice) ||
            !['auto', 'English', 'Chinese', 'Japanese', 'Korean', 'German', 'French', 'Russian', 'Portuguese', 'Spanish', 'Italian'].includes(args.language))) fail('speech requires a registered voice ID and language');
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
              ...(kind === 'speak' ? { speech: { voice: args.voice, language: args.language } } : {}),
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
    if (!['analyst', 'coder', 'document'].includes(args.subagent_type)) fail('specialist must be analyst, coder or an explicitly authorised document edit');
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
    tool: { local_image: mediaTool('image'), local_video: mediaTool('video'), local_speech: mediaTool('speak') },
    async config(config) {
      // Base configuration denies task. Only successful plugin initialization
      // enables it, so a missing/broken policy file cannot allow unbounded work.
      config.tools.task = true;
      config.tools.local_image = true;
      config.tools.local_video = true;
      config.tools.local_speech = true;
      for (const name of ['plan', 'build']) {
        config.agent[name].permission.task = { '*': 'deny', analyst: 'allow', coder: 'allow', document: 'allow' };
        config.agent[name].permission.local_image = 'ask';
        config.agent[name].permission.local_video = 'ask';
        config.agent[name].permission.local_speech = 'ask';
      }
    },
    async 'chat.message'(input, output) {
      const session = data(await client.session.get({ path: { id: input.sessionID } }));
      if (session.parentID) {
        if (output.parts.some(p => p.type !== 'text')) fail('specialist input must be supplied text only');
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
        ledger.turns[key] = { calls: [], ...(essay ? {essay} : {}) };
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
      const role = ['plan', 'build'].includes(input.agent) ? 'coordinator' : input.agent;
      if (roles[role] && (input.model.providerID !== 'local-ai-gateway' || input.model.id !== roles[role])) {
        fail('agent model changed; use the configured role');
      }
    },
    async 'tool.execute.before'(input, output) {
      const session = data(await client.session.get({ path: { id: input.sessionID } }));
      if (session.parentID || input.tool !== 'task') {
        const messages = data(await client.session.messages({ path: { id: input.sessionID } }));
        const assistant = messages.find(m => m.info.role === 'assistant' && m.parts.some(p =>
          p.type === 'tool' && (p.callID === input.callID || p.id === input.callID)));
        if (assistant?.info.agent === 'coder') return coderTool(input, session, messages, assistant);
        if (session.parentID) fail('non-coder specialists cannot use tools or delegate');
      }
      if (input.tool !== 'task') return;
      await exclusive(async () => {
        await checkMode();
        const { key, messages, sourceMessages } = await identity(input);
        const turn = ledger.turns[key] ?? { calls: [] };
        if (turn.calls.some(c => c.id === input.callID)) fail('duplicate call already consumed its attempt');
        if (turn.essay && output.args.subagent_type !== 'document') fail('essay turns use the tool-free document specialist only');
        let essayRequest;
        if (output.args.subagent_type === 'document') {
          if (!roles.document || !turn.essay) fail('document editing requires an explicit ESSAY_EDIT request in this user turn');
          essayRequest = await loadRequest(turn.essay);
          let supplied;
          try { supplied = JSON.parse(output.args.prompt); } catch { fail('document prompt must be JSON; use {} on the first attempt'); }
          if (!supplied || Array.isArray(supplied) || Object.keys(supplied).some(k => k !== 'retry_failure')) fail('document draft and permissions come only from the saved user request');
          output.args.prompt = JSON.stringify(makeContract(essayRequest, supplied.retry_failure));
          if (output.args.prompt.length > MAX_INPUT) {
            turn.essay.status = 'incomplete_input_limit'; await save();
            fail('essay does not fit the handoff; original preserved. Submit a separately scoped section, no silent truncation.');
          }
        }
        const value = envelope(output.args);
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
        if (turn.calls.some(c => c.role === output.args.subagent_type) && !value.retry_failure) {
          fail('a repeated specialist requires retry_failure describing the concrete failure');
        }
        const contract = bindContract(value, sourceMessages);
        const acceptanceHash = hash(JSON.stringify(contract.acceptance));
        const prior = turn.calls.find(c => c.role === output.args.subagent_type);
        if (prior && prior.acceptance_hash !== acceptanceHash) fail('retry must preserve the original acceptance checklist');
        contract.return_format = RESULT_INSTRUCTION;
        if (essayRequest) {
          contract.essay_mode = 'copyedit-v1';
          contract.return_format += ESSAY_RETURN;
        }
        const packet = JSON.stringify(contract).replaceAll('@', '\\u0040');
        if (packet.length > MAX_INPUT) {
          if (essayRequest) {turn.essay.status = 'incomplete_input_limit'; await save();}
          fail('bound handoff exceeds 12000 characters; use a smaller explicitly scoped brief. The document agent cannot read file references.');
        }
        const saved = await saveArtifact(join(dirname(ledgerPath), 'handoff-contracts'),
          hash(key + input.callID) + '.json', contract);
        output.args.prompt = packet;
        turn.calls.push({ id: input.callID, role: output.args.subagent_type, status: 'reserved',
          acceptance_hash: acceptanceHash, contract_file: saved.path, contract_sha256: saved.sha256 });
        ledger.turns[key] = turn;
        await save();
        active.set(input.sessionID, input.callID);
      });
    },
    async 'tool.execute.after'(input, output) {
      if (input.tool !== 'task') return;
      const { key } = await identity(input);
      const call = ledger.turns[key].calls.find(c => c.id === input.callID);
      if (!call?.contract_file) fail('return has no saved acceptance contract');
      const text = await readFile(call.contract_file, 'utf8');
      if (hash(text) !== call.contract_sha256) fail('saved acceptance contract changed');
      const contract = JSON.parse(text);
      let raw = output.output;
      let tools = [];
      const sourceIssues = [];
      const childID = output.metadata?.sessionId;
      if (!childID) sourceIssues.push('Native child session identity missing.');
      else {
        const child = data(await client.session.get({ path: { id: childID } }));
        if (child.parentID !== input.sessionID) fail('return belongs to another parent');
        const messages = data(await client.session.messages({ path: { id: childID } }));
        const final = messages.findLast(m => m.info.role === 'assistant');
        raw = final?.parts.filter(p => p.type === 'text').map(p => p.text).join('\n') ?? '';
        tools = messages.flatMap(m => m.parts).filter(p => p.type === 'tool');
        if (!final || final.info.error || final.info.finish === 'length') sourceIssues.push('Specialist response missing, failed or cut off.');
      }
      const report = assessResult(contract, raw, tools, sourceIssues);
      if (call.role === 'document') {
        const record = ledger.turns[key].essay;
        const request = await loadRequest(record);
        report.essay = await persistResult(record, input.callID, request, raw, report.issues.concat(
          report.acceptance.filter(c => c.status !== 'met').map(c => 'Unmet or unverified acceptance item: ' + c.id)));
        report.status = report.essay.status;
        report.issues.push(...report.essay.issues);
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
      output.output = JSON.stringify({ status: report.status, ...(report.essay ? {essay:report.essay} : {}),
        summary_excerpt: report.summary.slice(0, 1600), summary_shortened: report.summary.length > 1600,
        acceptance: report.acceptance.map(c => ({ id: c.id, status: c.status, basis: c.basis })),
        issues: report.issues.slice(0, 12), full_report: artifact.path, sha256: artifact.sha256,
        instruction: 'Read the full report before claiming completion. It preserves the exact checklist, complete specialist result and native tool evidence. Review every criterion; needs_attention is not completion. Native execution alone does not prove correctness.' });
      output.metadata = { ...output.metadata, localTeamReview: report.status, localTeamReport: artifact.path,
        localTeamReportSha256: artifact.sha256 };
    },
    async 'tool.definition'(input, output) {
      if (input.toolID !== 'task') return;
      output.description += '\nLocal team: at most two foreground attempts per user turn. Analyst or coder; document only for an explicit ESSAY_EDIT user request. For document, prompt is {} or {retry_failure:concrete failure}; host supplies the preserved draft, permissions and contract. Do not construct or change its evidence. Other roles: '
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
