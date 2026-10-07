// Deterministic handoff checks. A well-formed claim is not proof of correctness.
import { createHash } from 'node:crypto';
import { mkdir, lstat, open, readFile } from 'node:fs/promises';
import { join } from 'node:path';

export const hash = value => createHash('sha256').update(value).digest('hex');
const fail = message => { throw new Error('Handoff contract: ' + message); };
const strings = (value, name, max = 12) => {
  if (!Array.isArray(value) || value.length > max || value.some(x => typeof x !== 'string' || x.length > 2000)) {
    fail(name + ' must be a bounded string list');
  }
};
const pathOK = path => typeof path === 'string' && path.length > 0 && path.length <= 400 &&
  !path.startsWith('/') && !path.includes('\\') && !path.split('/').includes('..') && !/[\x00-\x1f]/.test(path);

export function validateContract(value) {
  for (const name of ['facts', 'assumptions', 'unknowns']) strings(value[name], name);
  if (!Array.isArray(value.references) || value.references.length > 12 || value.references.some(r =>
    !r || !pathOK(r.path) || typeof r.symbol !== 'string' || r.symbol.length > 200 ||
    Object.keys(r).some(k => !['path', 'symbol'].includes(k)))) fail('references require relative project paths and symbols');
  if (!Array.isArray(value.acceptance) || !value.acceptance.length || value.acceptance.length > 8) fail('supply 1–8 acceptance criteria');
  const ids = new Set();
  for (const item of value.acceptance) {
    if (!item || !/^A[1-8]$/.test(item.id) || ids.has(item.id)) fail('criterion IDs must be unique A1–A8');
    ids.add(item.id);
    if (Object.keys(item).some(k => !['id', 'requirement', 'source_quote', 'verification'].includes(k))) fail('unknown criterion field');
    if (typeof item.requirement !== 'string' || !item.requirement.trim() || item.requirement.length > 1200 ||
        typeof item.source_quote !== 'string' || item.source_quote.length > 1200) fail('invalid criterion text');
    if (item.source_quote && item.requirement !== item.source_quote) fail('quoted requirements must be preserved verbatim');
    const check = item.verification;
    if (!check || !['test', 'inspection', 'analysis'].includes(check.kind) || typeof check.command !== 'string' ||
        check.command.length > 2000 || Object.keys(check).some(k => !['kind', 'command'].includes(k)) ||
        (check.kind === 'test' ? !check.command.trim() : check.command !== '')) fail('invalid criterion verification');
  }
}

export function bindContract(value, sourceMessages) {
  const result = structuredClone(value);
  result.acceptance = result.acceptance.map(item => {
    if (!item.source_quote) return { ...item, source: { kind: 'derived' } };
    const source = sourceMessages.find(m => m.parts.some(p => p.type === 'text' &&
      !p.synthetic && typeof p.text === 'string' && p.text.includes(item.source_quote)));
    if (!source) fail('source_quote is not present verbatim in an explicit user message');
    return { ...item, source: { kind: 'user_quote', message_id: source.info.id } };
  });
  return result;
}

export const RESULT_INSTRUCTION = 'For delegated work, return one JSON object (no markdown fence): '
  + '{"summary":"...","acceptance":[{"id":"A1","status":"met|unmet|blocked|unverified",'
  + '"evidence":"...","tool_call_ids":[]}],"changed_files":[],"tests":['
  + '{"tool_call_id":"native call ID or empty when not run","command":"exact command",'
  + '"status":"passed|failed|not_run"}],"assumptions":[],"unresolved":[]}. '
  + 'Address every supplied acceptance ID exactly once. Do not rewrite the requirements. '
  + 'Test criteria need actual matching command execution; inspection criteria need actual read/grep/glob calls. '
  + 'If native tool IDs are unavailable, report unverified instead of inventing IDs. '
  + 'Analysis evidence is your claim, not independent verification. Keep full changes in project files.';

export function assessResult(contract, raw, toolParts, sourceIssues = []) {
  const issues = [...sourceIssues];
  let result;
  try { result = JSON.parse(raw); } catch { issues.push('Specialist did not return valid result JSON.'); }
  const observed = toolParts.filter(p => p.type === 'tool').map(p => ({
    id: p.callID, tool: p.tool, status: p.state?.status,
    command: p.state?.input?.command, exit: p.state?.metadata?.exit,
  }));
  const commandRun = (id, command, status) => observed.find(t => t.id === id && t.tool === 'bash' &&
    t.status === 'completed' && t.command === command && typeof t.exit === 'number' &&
    (status === 'passed' ? t.exit === 0 : t.exit !== 0));
  const rows = Array.isArray(result?.acceptance) ? result.acceptance : [];
  if (!result || typeof result !== 'object' || Array.isArray(result) || typeof result.summary !== 'string') {
    issues.push('Result summary is missing.');
  }
  for (const key of ['changed_files', 'assumptions', 'unresolved']) {
    if (!Array.isArray(result?.[key]) || result[key].length > 40 || result[key].some(x => typeof x !== 'string')) {
      issues.push('Invalid result field: ' + key);
    }
  }
  if (Array.isArray(result?.changed_files) && result.changed_files.some(p => !pathOK(p))) issues.push('Changed-file references must be relative project paths.');
  if (!Array.isArray(result?.tests) || result.tests.length > 24) issues.push('Invalid test report.');
  const tests = Array.isArray(result?.tests) ? result.tests.map(t => {
    const valid = t && typeof t.command === 'string' && typeof t.tool_call_id === 'string' &&
      ['passed', 'failed', 'not_run'].includes(t.status);
    const verified = valid && t.status !== 'not_run' && !!commandRun(t.tool_call_id, t.command, t.status);
    if (!valid || (t.status !== 'not_run' && !verified)) issues.push('Test claim lacks matching native command/exit evidence.');
    return { ...t, execution_verified: verified };
  }) : [];
  const known = new Set(contract.acceptance.map(c => c.id));
  if (rows.some(r => !r || !known.has(r.id))) issues.push('Result contains unknown acceptance IDs.');
  const acceptance = contract.acceptance.map(criterion => {
    const matches = rows.filter(r => r?.id === criterion.id);
    const row = matches[0];
    let status = row?.status;
    let basis = 'specialist_claim';
    if (matches.length !== 1 || !['met', 'unmet', 'blocked', 'unverified'].includes(status) ||
        typeof row?.evidence !== 'string' || !Array.isArray(row?.tool_call_ids) ||
        row.tool_call_ids.some(id => typeof id !== 'string')) {
      status = 'unverified'; issues.push('Missing or malformed criterion result: ' + criterion.id);
    } else if (status === 'met') {
      if (!row.evidence.trim()) {
        status = 'unverified'; issues.push('Missing evidence for ' + criterion.id);
      } else if (criterion.verification.kind === 'test') {
        const match = tests.find(t => t.execution_verified && t.status === 'passed' &&
          t.command === criterion.verification.command && row.tool_call_ids.includes(t.tool_call_id));
        if (!match) { status = 'unverified'; issues.push('Required test execution unverified: ' + criterion.id); }
        else basis = 'native_command_exit_zero';
      } else if (criterion.verification.kind === 'inspection') {
        if (!observed.some(t => row.tool_call_ids.includes(t.id) && ['read', 'glob', 'grep'].includes(t.tool) && t.status === 'completed')) {
          status = 'unverified'; issues.push('File inspection unverified: ' + criterion.id);
        } else basis = 'native_inspection_recorded';
      }
    }
    return { ...criterion, status, evidence: typeof row?.evidence === 'string' ? row.evidence : '', basis };
  });
  if (result?.unresolved?.length) issues.push('Specialist reports unresolved issues.');
  return { version: 1, status: issues.length || acceptance.some(c => c.status !== 'met') ? 'needs_attention' : 'ready_for_review',
    summary: typeof result?.summary === 'string' ? result.summary : '', acceptance, tests, issues,
    changed_files: Array.isArray(result?.changed_files) ? result.changed_files : [],
    assumptions: Array.isArray(result?.assumptions) ? result.assumptions : [],
    unresolved: Array.isArray(result?.unresolved) ? result.unresolved : [], observed_tools: observed,
    contract, raw_result: raw,
    caveat: 'Recorded tool execution does not prove test adequacy or semantic correctness. Analysis and file claims need review.' };
}

export async function saveArtifact(directory, name, value) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const info = await lstat(directory);
  if (!info.isDirectory() || info.isSymbolicLink()) fail('artifact directory must be a real directory');
  const content = JSON.stringify(value, null, 2) + '\n';
  const file = join(directory, name);
  try {
    const handle = await open(file, 'wx', 0o600);
    try { await handle.writeFile(content); await handle.sync(); } finally { await handle.close(); }
  } catch (error) {
    if (error.code !== 'EEXIST' || (await lstat(file)).isSymbolicLink() || await readFile(file, 'utf8') !== content) throw error;
  }
  return { path: file, sha256: hash(content) };
}
