// OpenCode v1.18.34 policy hooks. Native task owns the child session/tool loop.
// No inference calls, account credentials or source text are stored here.
import { readFile, open, rename } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname } from 'node:path';

const MAX_INPUT = 12000;
const MAX_RESULT = 12000;
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
  }
  await save();
  return { ledger, exclusive, save, active: new Map() };
}

export default async function LocalTeam({ client }, options = {}) {
  const { ledgerPath, roles, modeToken } = options;
  if (!ledgerPath || !roles?.coordinator || !roles?.analyst || !roles?.coder || !modeToken) fail('configuration missing');
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
    return { key, messages };
  }

  function envelope(args) {
    if (!['analyst', 'coder'].includes(args.subagent_type)) fail('specialist must be analyst or coder');
    if (args.task_id || args.background || args.command) fail('resuming, commands and background delegation are disabled');
    if (typeof args.description !== 'string' || args.description.length > 160) fail('description exceeds 160 characters');
    if (typeof args.prompt !== 'string' || args.prompt.length > MAX_INPUT) fail('handoff exceeds 12000 characters');
    let value;
    try { value = JSON.parse(args.prompt); } catch { fail('prompt must be a JSON handoff envelope'); }
    if (!value || Array.isArray(value) || typeof value !== 'object') fail('invalid handoff envelope');
    if (Object.keys(value).some(k => ![...fields, 'retry_failure'].includes(k))) fail('unknown handoff field');
    for (const field of fields) {
      if (typeof value[field] !== 'string') fail('handoff requires string field: ' + field);
    }
    if (!value.objective.trim() || !value.result.trim()) fail('objective and result must be explicit');
    if (value.retry_failure !== undefined && (typeof value.retry_failure !== 'string' || !value.retry_failure.trim())) fail('retry needs a concrete failure');
    // Native task resolves @file references before inference. Escaped JSON keeps
    // supplied evidence literal and prevents implicit file/agent attachments.
    args.prompt = JSON.stringify(value).replaceAll('@', '\\u0040');
    return value;
  }

  return {
    async config(config) {
      // Base configuration denies task. Only successful plugin initialization
      // enables it, so a missing/broken policy file cannot allow unbounded work.
      config.tools.task = true;
      for (const name of ['plan', 'build']) {
        config.agent[name].permission.task = { '*': 'deny', analyst: 'allow', coder: 'allow' };
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
        ledger.turns[key] = { calls: [] };
        await save();
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
      const value = envelope(output.args);
      await exclusive(async () => {
        await checkMode();
        const { key, messages } = await identity(input);
        const turn = ledger.turns[key] ?? { calls: [] };
        if (turn.calls.some(c => c.id === input.callID)) fail('duplicate call already consumed its attempt');
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
        turn.calls.push({ id: input.callID, role: output.args.subagent_type, status: 'reserved' });
        ledger.turns[key] = turn;
        await save();
        active.set(input.sessionID, input.callID);
      });
    },
    async 'tool.execute.after'(input, output) {
      if (input.tool !== 'task') return;
      await exclusive(async () => {
        for (const turn of Object.values(ledger.turns)) {
          const call = turn.calls.find(c => c.id === input.callID);
          if (call) call.status = 'completed';
        }
        await save();
        active.delete(input.sessionID);
      });
      if (output.output.length > MAX_RESULT) {
        output.output = output.output.slice(0, MAX_RESULT) + '\n[Handoff result clipped at 12000 characters. Full response remains in the child session. Do not treat this excerpt as complete.]';
        output.metadata = { ...output.metadata, localTeamClipped: true };
      }
    },
    async 'tool.definition'(input, output) {
      if (input.toolID !== 'task') return;
      output.description += '\nLocal team: at most two foreground attempts per user turn. Only analyst or coder. '
        + 'prompt must be JSON with string fields objective, constraints, evidence, completed, remaining, result. '
        + 'Supply actual excerpts in evidence; paths are references only. Maximum 12000 characters. '
        + 'A repeated role requires retry_failure describing a concrete failure. No task_id, command or background.';
    },
  };
}
