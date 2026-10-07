# Handoff implementation plan

Date: 2026-10-07. Status: planned, no runtime changes in this documentation commit.
Decision record: [MODEL-TEAM-AND-HANDOFFS.md](MODEL-TEAM-AND-HANDOFFS.md).
Target: 32 GB total unified memory, one active generative model at a time.

## Current implementation and gaps

| Area | Current code | Required change |
| --- | --- | --- |
| Presets and validation | installer/payload/text_models.py: old Qwen presets; context limited to 16K | Versioned team manifest, named role/profile mappings and selective context limits |
| Routing | installer/payload/routing.py: selected text preset and explicit slash commands | Explicit specialist route first; validated semantic routing later |
| Modes | installer/payload/resource_modes.py: Normal/Gaming eligibility hard-coded to old model tags | Validated role eligibility; preserve Gaming and media restrictions |
| Lifecycle | installer/payload/model_engine.py: one serial executor, unload confirmation, mode epoch | Profile-aware switching, delegations as separate jobs and accounting |
| HTTP/tools | http_api.py, tool_protocol.py and web_tools_api.py | Authenticated delegation endpoint, separate schema and strict envelope validation |
| WebUI integration | common.py and native OpenAPI/MCP tool sessions | Client-bound delegation adapter; native approval/result integration |
| OpenCode | work_agent.py: local provider; task tool explicitly disabled | Separate verified adapter or native facility; retain permission restrictions |
| Compaction | context_policy.py and context_settings.py: mode-level global WebUI cap | Per-role/profile native thresholds and correctly advertised input/output budgets |
| Installer | installer.py: configured model pulls, module manifest and acceptance fingerprint | Exact artifact resolution, reversible team migration and new acceptance checks |

Image/audio inputs currently fail in tool_protocol.py. Vision capability requires
an explicit image-input bridge; downloading a multimodal model alone does not
implement it. File references require existing permission-checked retrieval before
inference; the backend does not automatically open arbitrary paths.

## 1. Resolve artifacts and native client facilities

Before changing defaults, resolve the three selected variants to exact local
artifacts. Record source revision/digest, quantisation, template, thinking support,
tool format and native context metadata. Start with suitable 4-bit artifacts,
subject to conversion support; do not assume the full-precision coder fits.

Verify the coder's architecture is supported by the project's installed Ollama.
If a newer backend is necessary, treat it as a tested dependency upgrade with
checksum/signature checks and reversible private-app replacement. Retest native
truncate=false and shift=false behavior; never relax context protection to load
a candidate. Do not load arbitrary remote model code just to inspect metadata.

Inspect pinned WebUI/OpenCode native delegation facilities before writing a new
adapter. Reuse them only if they can select allowed local specialists, share the
lifecycle queue, preserve permissions and expose a stable originating turn ID.
WebUI has internal chat/message metadata, but that does not prove a generic
OpenAPI tool receives trustworthy turn identity. Prove the actual propagation
path. OpenCode task is currently disabled; do not enable unrestricted subagents.

Deliverable: pinned team manifest plus a documented native-adapter choice. Coder
role remains disabled if no compatible artifact is resolved. No silent fallback.

## 2. Add explicit role profiles and reversible migration

Extend preset configuration with validated coordinator, document, analyst and
coder mappings. Coordinator/document share the same 4B weights but use separate
context profiles. Adopt the decision record's 8K/32K/32K/16K targets; Gaming
clamps coordinator to 4K/1K and excludes every specialist.

Retain existing 1K/4K/8K mode output ceilings and smaller-context protections.
Context increase does not imply an output increase. Replace hard-coded tag-based
eligibility with explicit validated manifest/profile eligibility, not a permissive
"anything called small" naming rule. Unknown roles/models are rejected.

Migrate known stock configurations once with a private backup. Preserve custom
models, contexts, timeouts, credentials, workflows and disabled integrations.
Represent disabled/unavailable roles explicitly. Preserve legacy IDs where needed
for existing chats and provide a reversible feature flag for team routing.

Update context_policy.py, context_settings.py and work_agent.py together. The
current WebUI global-minimum cap would compact a 32K worker as early as the 8K
coordinator, so it is insufficient for this team. Use supported per-model/chat
metadata through the trusted adapter where available, with a safe global ceiling.
Do not mutate global settings on every request and race concurrent chats. If the
pinned client cannot apply independent budgets, expose explicit profiles and
retain conservative compaction until integration is verified. Backend overflow
rejection remains the hard boundary.

Deliverable: selectable profiles and accurate client budgets, without automatic
handoffs yet. Existing modes, media handoffs and custom configurations still work.

## 3. Implement the bounded handoff service

Introduce a pure handoff schema/policy module and a separate service adapter.
Illustrative module names are handoff_policy.py and handoff_service.py; these files
do not exist yet. Bound objective/evidence/result sizes to the existing HTTP and
context envelopes. Roles are allowlisted; no model-selected URLs or backends.

Provide a local authenticated endpoint such as POST /tools/delegate_local. Keep
it unavailable on the media listener and out of the VPN-retrieval schema. The
native client attaches a gateway-issued turn binding outside LLM arguments. Bind
it to the client user/session, originating user message, allowed parent and mode
epoch. Explicitly complete or expire turns, with bounded retention. Unknown or
missing bindings cannot delegate. Do not trust a client-supplied label alone as
proof of identity.

Account atomically for two specialist attempts, retry inclusion, depth one and
idempotency. Reserve before queuing. Reject nested delegation, stale mode epochs,
role changes and concurrent oversubscription. Preserve counters across reconnects
or require a fresh explicit user turn after recovery; gateway restart must not
silently authorize a third attempt for the same turn.

Specialists initially receive no delegation tools and no execution/account tools.
They return bounded analysis or proposed code. Running tests/editing remains with
the existing native client under its permissions; introducing specialist tool
sessions is a later, separately bounded step.

Deliverable: one authenticated explicit handoff round trip through mocked
inference, with reliable budget/identity enforcement and structured results.

## 4. Integrate lifecycle and native tool sessions

Run each specialist request as a new job on Engine's existing single executor.
The parent has already returned its tool call. Never wait recursively on the
same executor. Recheck mode at execution time, confirm outgoing weights unloaded,
then load the specialist. Block admission after unload failure. Reuse existing
ComfyUI teardown, mode_epoch invalidation and error/cutoff propagation.

Attach the delegation tool to eligible parent sessions only through the selected
native adapter. Preserve client approvals and normal conversation/tool history.
Supply identity from client metadata, not model-generated arguments. The initial
specialist tool policy is empty; removing tools is enforced in code.

Explicit /code or model selection can directly route a whole turn to the coder.
Ordinary delegated tool results return through the native parent loop; optional
skipping of parent synthesis needs a verified client completion path. Do not
implement a hidden inference loop to fake direct completion. Pin the selected
role throughout its subsequent client tool exchanges, rather than reclassifying
a tool result as a new request.

Deliverable: one saved WebUI turn delegates and resumes; direct coder requests
avoid a coordinator inference. OpenCode integration follows only after the WebUI
path and its identity/permissions have been verified.

## 5. Add semantic routing and conditional synthesis

Apply deterministic explicit routes first. For other tasks, run the 4B
coordinator in non-thinking mode with compact relevant state and a strict output
schema: direct, analyst, coder or a bounded mixed-task plan, plus a concrete
reason/deliverable. Validate role availability, budgets and mode before dispatch.
Invalid output stays with the coordinator; it cannot trigger an unbounded repair
loop. Quoted instructions and evidence do not override user intent or policy.

For mixed tasks, schedule no more than two specialist attempts sequentially.
Return results directly where the client supports it; otherwise provide one
necessary synthesis continuation. Do not invoke analyst synthesis as an extra
third specialist. A test failure can justify one retry only if budget remains.
Preserve exact acceptance criteria, source references and unresolved issues.

Deliverable: predictable routing with inspectable reasons and bounded failures.

## 6. Add image input and optional monitoring

Image support comes after text handoffs. Implement bounded OpenAI image-content
to Ollama conversion with supported formats and decoded-size limits. Use existing
attachment/vault permission paths, not arbitrary model-supplied network fetches.
Account for image tokens and preprocessing memory. Keep image understanding
separate from ComfyUI generation and existing Gaming restrictions.

Expose lightweight role/stage status and timing records if requested. Retain
buffered final answers. Record load_duration, prompt_eval_duration and generation
usage from backend responses, plus wall-clock unload/switch timing. Diagnostic
logs hold IDs/counters rather than source content or credentials.

Deliverable: visual document profile and optional non-inference progress polling.

## 7. Verify, package and accept on the Mac

Meaningful regression coverage must include:

- Per-turn accounting across concurrent requests, retries, replay, reconnect and
  stale mode epochs; missing identity and nested delegation rejected.
- No recursive-executor deadlock; unloading failure prevents specialist load;
  another queued task cannot violate the active-model limit.
- Gaming prevents analyst/coder access through every endpoint; Normal/Max keep
  existing media restrictions; custom configuration migration remains reversible.
- Tool permissions remain client-owned; specialists cannot invent execution
  claims, delegate, gain filesystem scope or start independent backends.
- Explicit routing stays stable through tool continuations; malformed semantic
  routes, unavailable specialists and oversized evidence fail predictably.
- Actual JSON/SSE tool IDs, structured errors, usage and length cutoffs survive
  delegation and return; handoff summaries preserve evidence references.
- Role-specific context/input/output limits are advertised and enforced, without
  global-setting races between chats or silent input trimming.

Run appropriate authoring suites and package checks. Add new modules to the
installer manifest, fingerprint all handoff/client configuration that affects
acceptance, update offline guides and rebuild the ZIP only when implementation
exists. This documentation change does not rebuild or claim a new runtime ZIP.

Native Mac acceptance measures exact artifacts: cold/warm loading, 4B -> 9B -> 4B
and 4B -> coder -> 4B wall-clock latency, first-response latency, memory pressure,
swap and one-model residency. Test the 8K/16K/32K profiles with normal background
apps; context tests must locate and combine evidence near beginning/middle/end,
not merely accept a large prompt. Test long code/document accuracy, real executed
tests, WebUI approval/reload and OpenCode permissions separately.

Compare direct single-model results against routed results on representative
user tasks. No hardware benchmark is a prerequisite for writing these planned
features, but unsupported artifacts cannot ship as working defaults, and native
performance/quality claims remain pending until measured. If pressure is high,
reduce per-role context first; do not disable GPU memory safeguards or silently
add resident models. Keep the old configuration available for rollback.

## Delivery order

First usable increment: pinned text roles, explicit /code routing and one bounded
WebUI specialist handoff with trustworthy turn accounting. Then semantic routing,
OpenCode integration, larger-context tuning and vision. Do not wait for every
future capability before producing a reviewable first increment.
