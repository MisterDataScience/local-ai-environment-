# Model team and handoff policy

Decision date: 2026-10-07. Target: a Mac mini with 32 GB total unified memory.
Status: agreed design, not implemented or hardware-validated. This document records
future implementation choices; it does not describe capabilities shipped in the
current installer. Implementation order is in
[HANDOFF-IMPLEMENTATION-PLAN.md](HANDOFF-IMPLEMENTATION-PLAN.md).

## Team

Prefer recent, capable models with abliterated variants. Select for useful task
performance within the memory budget rather than parameter count or novelty alone.
Abliteration reduces refusal behaviour; it does not establish higher capability.
The exact community variants need their own validation.

| Role | Selected candidate | Assigned work | Initial context target |
| --- | --- | --- | --- |
| Coordinator and routine worker | Huihui Qwen3.5 4B abliterated | Interpret requests, select a specialist, prepare bounded handoffs, answer routine questions, extract and summarise; visual reading after image support is added | 8,192 for coordination; 32,768 for document work |
| Analyst | Huihui Qwen3.5 9B abliterated | Difficult reasoning, planning, conflicting evidence, and substantial synthesis | 32,768 |
| Coder | Huihui Gemma 4 12B Coder Fable5 Composer2.5 v1 abliterated | Bounded implementation, debugging, tests and code explanation | 16,384 |

The Qwen candidates have published Ollama tags under
huihui_ai/qwen3.5-abliterated, with 4B and 9b variants. Installation must pin the
resolved artifact digest and inspect its template/capabilities; tag names alone
are not immutable. The coder's selected source is
huihui-ai/Huihui-gemma-4-12B-coder-fable5-composer2.5-v1-abliterated. Its exact
quantised artifact, digest and compatibility with the project's pinned Ollama
remain unresolved. Do not silently substitute the unmodified parent or a larger
model if installation fails. Mark that role unavailable until resolved.

The coordinator routes in non-thinking mode with a short structured request.
The analyst may use supported thinking mode. Model templates must preserve the
backend's required thinking/tool-call format. Role instructions do not make the
Qwen variants distinct specialist fine-tunes: their difference is capacity,
resource use and assigned work. The coder supplies task specialisation.

Qwen3.8 27B abliterated is excluded from the initial team. It remains an optional
future heavy fallback, not a default coordinator. Do not add another routing
model, embedding model or reasoning model to this first team without a concrete
need. Assess the existing WebUI retrieval integration before duplicating it.

The latest agreed context targets above supersede earlier exploratory 64K/128K
starting suggestions. Those larger windows are later experiments, not launch
defaults. Published Qwen limits are 262,144 tokens; supported length is not proof
of reliable recall or acceptable speed at that length. RAM saved by smaller
weights can fund more context, but context windows do not add together across
models. Runtime buffers, attention state, macOS and background applications all
share the same 32 GB.

## Routing decisions

| Request | Route |
| --- | --- |
| Routine conversation, rewriting, summaries or extraction | Coordinator answers directly; use its document profile only when input requires it |
| Explicit bounded coding request | Coder directly, avoiding a preliminary coordinator call |
| Difficult reasoning, conflicting evidence or complex planning | Analyst |
| Mixed task | Coordinator defines bounded subtasks; specialists work sequentially |
| Ambiguous request | Coordinator interprets; analyst only when interpretation needs harder reasoning |
| Visual evidence | Coordinator's visual/document profile, after image input is implemented |

For the first release, direct coding selection must be explicit: a chosen role
or a documented command such as /code. Code fences, quoted text, file extensions
or keywords alone must not silently determine the route. Automatic semantic
routing is a later step using a validated structured coordinator decision.
Unknown or malformed routing output stays with the coordinator and produces a
bounded answer or clarification within the client's normal conversation.

The coordinator should see the latest request plus compact relevant state. It
should not reread the entire archive just to choose a model. A choice to delegate
must identify a useful deliverable rather than request vague "more thinking".
The routing decision, selected role and reason should be inspectable through
optional status/history; final-answer buffering remains the user's preference.

## Handoff contract

A validated handoff carries:

| Field | Meaning |
| --- | --- |
| objective | Exact result required from the specialist |
| constraints | Requirements, exclusions and acceptance criteria |
| evidence | Bounded passages with source IDs or approved file references |
| completed_work | Established findings, kept separate from assumptions |
| remaining_work | Specific unresolved work |
| requested_result | Result shape, such as an explanation, proposed patch or analysis |

The gateway resolves the specialist from a role allowlist, not an arbitrary model
name supplied by the LLM. The client adapter attaches the turn identity and parent
call identity outside model-controlled arguments. Evidence text is untrusted data;
its embedded instructions cannot change roles, budgets, permissions or routing.
Source references confer no new filesystem/account access.

The specialist returns a structured result containing status, deliverable,
evidence references, assumptions, unresolved issues, and validation actually
performed. A text-only specialist can propose tests or patches; it cannot claim
it ran tests. Source files and original evidence stay available in their existing
storage locations. A summary is a working aid, not a replacement for originals.

Return to the coordinator only when synthesis is needed. A complete direct coding
answer can go to the user without another model load. Client formatting may still
be needed; do not pretend that a tool-result card automatically replaces the
client's final assistant response. A delegated result inside a native tool loop
normally returns to its parent unless a supported client adapter can complete the
turn directly. More difficult synthesis can be assigned to the analyst within
the same call budget.

## Execution and limits

1. The parent inference finishes by returning a delegation tool call. It releases
   its serial execution slot before any specialist is queued.
2. The native client tool loop invokes the authenticated delegation adapter.
3. The adapter validates the handoff and reserves its turn budget atomically.
4. The gateway rechecks mode eligibility, unloads the outgoing model and confirms
   it has left the loaded-model list before loading the specialist.
5. One specialist inference runs through the existing serial queue.
6. The adapter records the result and returns it to the native client. A return
   inference reloads the parent only if the workflow requires it.

Never call submit(...).result() on the same single-worker executor from inside
its running parent task. That can deadlock. Do not add a private autonomous agent
loop or let a tool start an independent Ollama/ComfyUI process.

| Limit | Agreed decision |
| --- | --- |
| Active generative models | One at a time; preserve serial media handoffs |
| Specialist attempts | At most two per user turn, including a retry |
| Delegation depth | One; specialists cannot delegate |
| Retry | At most one, only for concrete failure and only within the two-attempt budget |
| Failure evidence | A failed executed test, explicit context error or invalid result; confidence alone is insufficient |
| Context overflow | Retrieve/supply a smaller relevant section, or return a clear context error; never trim silently |
| Gaming | Coordinator only, at most 4K context and 1K output; no specialist loads |
| Normal/Max | Core team sequentially, subject to validated role profiles; retain existing media-mode restrictions |
| External tools | Existing client permissions and approvals remain authoritative |

Two independent specialist calls consume the whole budget, leaving no retry.
A direct specialist route counts as a specialist attempt. Ordinary parent
continuation is not another specialist attempt; native client loop limits still
bound coordinator continuation. Use operation IDs for deduplication so repeated
HTTP delivery cannot consume a new attempt or rerun completed work.

A per-turn budget must be associated with a real originating user turn, not a new
ID invented by the model on each tool call. Concurrent calls require atomic
accounting. Mode changes invalidate outstanding routing/handoff bindings; errors
must not reset the budget. Unsupported clients without a trustworthy turn binding
must not expose delegation as though those limits were enforced.

## Storage and observability

Record role selection, timestamps, mode, attempt count, outcome, error/cutoff,
actual token usage and available load/prompt/generation timings. Store full
handoff contents through the existing client conversation store or explicitly
configured workspace storage. Never include document contents or credentials in
routine diagnostic logs. Match existing local/vault boundaries; this design does
not make live chat history encrypted automatically.

An optional monitor may show the current role and stage. Poll existing lightweight
status; do not add a second inference to narrate progress. Buffer final text as
before. Unloading normally discards inference context state, so returning models
must process their supplied context again. Keep handoffs short and avoid switching
for every small reasoning step.

## Evidence and unresolved acceptance

- [Huihui Qwen3.5 Ollama variants](https://ollama.com/huihui_ai/qwen3.5-abliterated)
- [Selected coder variant](https://huggingface.co/huihui-ai/Huihui-gemma-4-12B-coder-fable5-composer2.5-v1-abliterated)
- [Coder parent context claim](https://huggingface.co/yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1)
- [Qwen3.5 4B configuration](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/config.json)
- [Qwen3.5 9B configuration](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/config.json)
- [Ollama loading and prompt timings](https://docs.ollama.com/api/chat)

The role assignments are decisions, not evidence of superiority. No exact-team
M6 throughput, switching latency, long-context accuracy or peak memory result is
available. Existing 155 passing authoring tests predate this design and do not
validate handoffs. Existing native context protection and output handling remain
implemented; delegation, semantic routing, this model migration and image input
remain planned.
