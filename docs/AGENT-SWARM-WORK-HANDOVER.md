# LOCAL AI: Adaptive Agent Swarms and Shared Inference

**Investigation handover for GPT Work**  
**Prepared:** 13 October 2026  
**Project:** [MisterDataScience/local-ai-environment-](https://github.com/MisterDataScience/local-ai-environment-)  
**Status:** Architecture review requested. No implementation authorised.

> **Decision to investigate**  
> Should LOCAL AI evolve from a single-worker, sequential specialist system into an adaptive system that can run one to five independent task agents, preferably sharing model weights and selectively using concurrent inference? Determine whether this would produce measurable improvements on the owner's Mac without compromising safety, privacy, responsiveness or existing functionality.

## 1. Instructions for GPT Work

Investigate this proposal against the **actual current `main` branch**, rather than relying on this handover as proof of current code. Read the source, configuration, tests and documentation. Distinguish existing implementation, documented intent, performance claims from outside projects, and your own proposed design.

**Primary assignment:** Produce a decision-quality technical assessment, not a speculative redesign. Compare incremental concurrency upgrades with a full agent-swarm re-architecture. Analyse real user workflows, propose tests that can be run on the owner's Mac, and recommend whether to proceed, how far, and in what order.

**Do not modify, commit, merge, publish, deploy, download large model weights or change configuration without a separate explicit instruction.** Do not treat access to the GitHub repository as authority to edit it. Read-only inspection and a written proposal are the authorised scope.

**Deliverables for the Work review:**

1. A source-traced **as-is architecture** and a technically coherent **proposed architecture**, showing request lifecycle, model loading, agent lifecycle, queueing, tool calls, cancellation and resource-mode gates.
2. A comparison of at least five deployment designs, including maintaining the current system, tool-task concurrency without parallel decoding, shared-model concurrency, streamed MoE inference, and hybrid specialist routing.
3. A worked example based on the MiniCPM discussion in this handover, showing when one, two, three or five agents would produce better outcomes and when parallelism creates overhead or correlated errors.
4. A repository change-impact inventory with file paths, interfaces, invariants, tests and migration/rollback requirements. Classify each as keep, adapt, replace or new.
5. A benchmark and acceptance plan designed for the **actual 32 GB Mac**, including meaningful workload success measures rather than tokens/second alone.
6. A recommended staged implementation plan, a risk register, clear decision gates and a final **proceed / prototype only / do not proceed** judgment with justification.

## 2. Owner's goal and hardware constraints

The owner wants LOCAL AI to perform substantial local work independently, with a possible team of simultaneous agents, without cloud outsourcing, avoidable recurring cost or indiscriminate tool access. Five concurrent agents is an **exploration target**, not a mandatory default. The desired improvement is useful work completed, not merely more concurrent model sessions.

**Owner-reported device:** M6 Mac mini, 32 GB unified memory, 256 GB internal SSD. The exact chip variant, actual storage bandwidth, usable free space, thermal behaviour and installed software state must be checked on the owner machine; no live benchmarking has yet been supplied. External SSD capacity may be available, but performance and location of model files should be measured, not assumed.

Do not treat 3 GB as the verified *total RAM required per MiniCPM agent*. The phone demonstration appears to describe a specialised expert-cache budget. Model weights, resident components, KV/context caches, runtime allocations and macOS still consume memory. Similarly, five contexts can be active without five generation streams running at full speed.

## 3. Current LOCAL AI architecture: facts to verify in code

The repository's `README.md` identifies `main` as the single installation source, and the built installation artefact as `downloads/Mac-Local-AI-Automated-Installer.zip`. It explicitly states that native acceptance on the owner's Mac remains required. The current repository documentation describes the following architecture:

| Area | Current design | Relevant sources |
|---|---|---|
| User interfaces | Open WebUI for chat; OpenCode Work Agent for project tasks; local conversation/voice and other entry points | `README.md`, `docs/WORK-AGENT.md`, `docs/architecture/CONNECTED_SYSTEM_MAP.md` |
| Shared backend | Local Python gateway exposing OpenAI-compatible `/v1` requests, mediating modes and Ollama inference | `installer/payload/model_engine.py`, `docs/architecture/CONNECTED_SYSTEM_MAP.md` |
| Inference admission | `ThreadPoolExecutor(max_workers=1)` and bounded admission; all heavy inference operations are serialised | `installer/payload/model_engine.py` |
| Ollama limits | `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_NUM_PARALLEL=1` | `installer/common.py` |
| Specialist team | Qwen3.5 4B coordinator, Qwen3.5 9B analyst, Gemma 4 12B coding specialist; document profile reuses the 4B weights | `installer/payload/model_team.py`, `docs/MODEL-TEAM-AND-HANDOFFS.md` |
| Context targets | Coordinator 8K, analyst 32K, coder 16K, document 32K | `installer/payload/model_team.py` |
| Handoffs | Native OpenCode child task sessions; foreground and sequential; two specialist attempts per user turn; depth one; no nested/background specialist delegation | `docs/WORK-AGENT.md`, `docs/MODEL-TEAM-AND-HANDOFFS.md` |
| Media/voice | ComfyUI image/video rendering and speech workers subject to explicit shared/exclusive memory and mode rules | `installer/payload/model_engine.py`, `docs/architecture/CONNECTED_SYSTEM_MAP.md` |
| Tooling | Playwright through VPN, AIOffice MCP, PDFKit/Apple Vision, local project transfers, vault tools, restricted desktop actions, selected GitHub and other integrations | `README.md`, `docs/SCOPED-AUTOMATION.md`, `docs/WORK-AGENT.md` |
| Background tasks | Checkpointed, finite, text-only document batch jobs, **not** general unattended agent loops | `docs/AUTONOMOUS-JOBS.md` |

The existing system therefore has **agent roles** but not a genuinely concurrent multi-agent execution layer. Some requests can be queued, but only one heavy inference operation is executed at a time. Switching to a different model/profile can unload the previous context and weights. This should not be confused with the user interface supporting simultaneous chats.

**Do not discard what already works:** the gateway admission boundary, OpenCode native permission loop, mode switching, specialist handoff contracts, per-turn budgets, model manifest checks, project-copy protection, tool adapters and explicit approval flows represent substantial existing engineering.

### Existing safety boundaries that must survive

- Gaming / Normal / Max resource modes, including mode-epoch invalidation and model unload barriers.
- No uncontrolled heavy-model overlap with ComfyUI, speech workers or other resource-exclusive services.
- Local-only inference and existing network/VPN restrictions; no silent direct-network browser fallback.
- Native OpenCode approvals for edits and shell commands, bounded project scope and preservation of original source projects.
- Scoped desktop/external automation's deliberately separate permission profile; concurrency must not re-enable disabled tools or bypass the guard.
- Strict turn-bound delegation accounting and restart/replay resistance. Parent-child task identity must stay authoritative.
- Sensitive material kept out of diagnostic logs; no assumption that plain project copies or handoff JSON are encrypted; no automatic vault unlock.
- Existing stop, failure, restart, safe-upgrade and rollback semantics. Concurrent agents must not bypass cancellation or continue acting after resource-mode changes.

## 4. The proposed change, defined carefully

Three forms of concurrency must be assessed **separately**:

**A. Workflow concurrency:** independent research, browser requests, file inspection, test runs or document-processing stages overlap while the generative model remains serial. This may be the cheapest first improvement.

**B. Shared-model session concurrency:** multiple task agents use one loaded model with independent instructions, KV caches and conversation states. The inference server may queue or batch their decoding. Sharing weights can reduce duplication, but KV memory rises with contexts.

**C. Actual concurrent inference:** multiple active requests are processed together with batching or simultaneous execution. Aggregate throughput and per-request latency must be measured. Five active agent sessions do **not** imply five times the token rate.

A fourth option, **separate resident or streamed model instances**, can be tested as a comparator, not assumed optimal. Five 3 GB expert caches are neither a measured total memory requirement nor evidence of five independent full-speed models.

**Preferred concept to evaluate:** an *adaptive task-graph scheduler* that selects one agent for routine questions, a few independent workers for decomposable research/audits, and up to five only when the work and measured resources justify it. Agent count, number of loaded models and decoding concurrency are distinct knobs.

### Candidate execution patterns

| Pattern | Potential gain | Principal cost / hazard |
|---|---|---|
| 1 agent, as today | Simple, predictable, low overhead | Independent work waits in sequence |
| 2-3 agents with serial inference | Concurrent tools, independent evidence | More task-state management without parallel tokens |
| Shared-model multi-slot inference | Shared weights and overlapping decoding | KV growth, slower individual streams, context/slot limits |
| SSD-streamed MoE shared across agents | Potentially larger model within a modest memory budget | SSD contention, expert-cache thrashing, prompt latency, implementation maturity |
| Hybrid existing specialists plus dynamic workers | Preserve coding/document strengths | Model swaps and heterogeneous resource scheduling |
| 5 separate model processes | Process isolation, independent runtimes | Likely weight/cache duplication and device contention |

## 5. Worked example: this MiniCPM / agent-swarm conversation

This discussion moved from a claimed 35B iPhone model running with a very small expert cache to questions about Mac storage, memory, concurrent inference and redesigning LOCAL AI. A single assistant researched these questions serially and progressively revised its understanding.

Five *possible* independent investigations would have been:

| Temporary agent | Bounded work package | Evidence needed |
|---|---|---|
| Technical verifier | Determine what MiniCPM's ~3 GB figure actually refers to; total memory, storage format and demo limitations | Official implementation code, documentation, instrumented metrics |
| Runtime researcher | Compare Ollama/llama.cpp/MLX and Mac-oriented SSD-streamed MoE implementations | Supported features, batching semantics, measured prompt/decode performance |
| Repository auditor | Locate LOCAL AI serial queues, model admission, OpenCode budget and safety constraints | Exact `main` branch paths, relevant functions and tests |
| Skeptical reviewer | Test the assumption that five agents outperform one; quantify KV, bandwidth, I/O and coordination risks | Independent sources and proposed falsifiable tests |
| Use-case analyst | Identify local workflows that divide well: code audits, long research, conversation archives and document batches | Task DAGs, time budgets, output-quality and merge requirements |

These workers could investigate in parallel while one coordinator merges findings and explicitly resolves contradictions. This **might** catch incorrect memory assumptions sooner and reduce research wall time. It is not a guarantee: identical models may share errors, shared browsing may hit limits, and five research packets may cost more than a focused three-agent plan.

Compare the same conversation using **one, two, three and five** workers. Estimate orchestration/model-call overhead, work redundancy and likely critical-path time. The decision should favour **quality of verified conclusions and time-to-useful-answer**, not maximum worker count.

### Other actual LOCAL AI use cases to assess

**Strong candidates:** independent codebase submodule audits; source cross-checks; independent documents or transcript shards; separate read-only inspection tasks; parallel tool I/O while inference continues elsewhere.

**Conditional candidates:** coding across isolated Git worktrees with merge review; preparing report evidence in parallel before a single coherent authorial pass; checking multiple hypotheses.

**Weak candidates:** ordinary chat, a single tightly coupled debugging thread, high-overhead multi-agent brainstorming without independent evidence, overlapping edits to the same file, or work that requires a shared mutable UI/session.

## 6. What the Work investigation must verify externally

The following are **leads**, not established suitability or native benchmark results for this Mac:

- [OpenBMB MiniCPM-V applications](https://github.com/OpenBMB/MiniCPM-V-Apps): iPhone implementation, model storage, 3 GB expert-cache interpretation, total process allocation and context limits.
- [OpenBMB MiniCPM-V project](https://github.com/OpenBMB/MiniCPM-V): architecture, model family, multimodal capability and official benchmarks.
- [Swift/Metal Slipstream](https://github.com/dwijenpatel/slipstream): low-resident-memory SSD-based expert streaming; investigate the documented request-serialisation limitation and long-prompt latency.
- [llama.cpp-based Slipstream fork](https://github.com/Schero94/slipstream): reported streaming support and OpenAI-compatible operation; independently inspect multi-request/batching behaviour.
- [llama.cpp server](https://github.com/ggml-org/llama.cpp): multiple slots, continuous batching and actual model compatibility.
- [Ollama documentation](https://docs.ollama.com/): `OLLAMA_NUM_PARALLEL` semantics, context memory cost and loaded-model policies.
- [MLX / mlx-lm](https://github.com/ml-explore/mlx-lm): current Apple Silicon inference and batching capabilities.

Record the **date and version/commit** tested for each. Do not combine benchmark figures from different runtimes, quantisations, Mac chips, cache sizes or prompt lengths. Do not infer that a model's advertised function calling, vision or coding benchmark means it can reliably operate the LOCAL AI tool stack.

## 7. Recommended benchmark design

The owner must run the native tests locally or grant Work access to an appropriately constrained environment. Repo-only analysis cannot measure Mac performance. Begin with isolated, read-only or disposable workloads before any real files or projects are touched.

**Baseline:** record current single-agent output quality, total task time, initial-token latency, model load/swap cost, prompt-processing throughput, decoding throughput and peak memory pressure.

**Experiment A: task concurrency only.** Keep one inference worker, overlap independent tool operations. Test read-only research and repository inspections. Determine whether total wall time improves without touching model backend rules.

**Experiment B: one resident model, multiple slots.** With an engine proven to support it, run 1, 2, 3 and 5 independent contexts. Use short and long prompts and context lengths relevant to the current 8K/16K/32K profiles. Compare both short answers and tool-heavy work.

**Experiment C: MoE streaming.** Benchmark a compatible MoE model with fully resident, partially cached and SSD-streamed setups. Separately test single-user latency and multi-request performance. Verify whether streaming and continuous batching work *together* on the selected runtime. Compare internal and external SSD where feasible.

**Experiment D: adaptive orchestration.** Evaluate one versus three versus five workers on the same reproducible code audit, evidence-gathering research task and multi-document batch. Score correct findings, supported citations, duplicate work, defects introduced and human intervention.

Measure: completed useful tasks/hour; end-to-end wall time; p50/p95 time to first token; aggregate and per-request decode rates; prompt processing; resident/unified memory, swap and memory pressure; SSD throughput and free space; CPU/GPU contention; tool wait; error/retry counts; cancellation latency; UI responsiveness; impact on Gaming/Normal/Max and speech/media workflows. Track both warm and cold runs.

**No-Go conditions:** evidence of leaked permissions/secrets, unapproved writes, broken mode transitions, resource-pressure instability, inability to cancel stale agents, unreliable result attribution, degradation of core workflows, or performance that is not meaningfully better than serial execution after accounting for coordination overhead.

Do not assign arbitrary speedup or memory thresholds as facts. Propose thresholds up front and explain how they correspond to the owner's priorities, then test against them.

## 8. Repository engineering questions to answer

Inspect exact ownership of these behaviours and propose minimally invasive changes:

1. **Admission and scheduling:** Can `installer/payload/model_engine.py` distinguish serial media work, concurrently safe tool operations and a multi-slot text inference backend without deadlocking or breaking epochs? How are mode transitions made atomic across active tasks?
2. **Provider configuration:** Where do `OLLAMA_NUM_PARALLEL`, model residency, per-context limits and keep-alive settings originate, and which tests assert them? What settings would require migration?
3. **OpenCode native task model:** Can the pinned OpenCode version support multiple read-only child tasks concurrently, with safe parent resumption and stable native session IDs? Would any change require an upstream update rather than a custom loop?
4. **Budgets and idempotency:** Can per-turn attempt limits be extended to a task graph without replays, reconnects, retries or background continuations evading enforcement?
5. **Shared context and artifacts:** How will agents access only the evidence needed, maintain source IDs, and produce versioned outputs without copying full archives or duplicating model prompts?
6. **Workspace isolation:** Can concurrent coding use separate copied workspaces or Git worktrees, with file ownership rules, tests and an explicit reviewed merge? Prevent edits to the owner's original source by default.
7. **Resource governance:** Who controls GPU, RAM, SSD, audio, ComfyUI and interactive priorities? How does the system pause background work when the owner requests chat, gaming, voice or video?
8. **Observability and failure recovery:** How to report active jobs, queue depth, resource consumption, task lineage and partial results without storing sensitive prompt data? What happens on crash, disconnect, timeout and cancel?
9. **Compatibility and rollback:** How can the existing one-model, one-request design remain an instantly recoverable supported mode? Which existing tests would be invalidated by an experimental scheduler?

## 9. Staged development recommendation to evaluate

**Stage 0: audit and baseline.** Verify the live repo, existing controls and Mac hardware. Establish reproducible workloads and measurement, without architecture changes.

**Stage 1: controlled parallel *tasks*.** Support small numbers of independent read-only tool tasks while leaving the model-serving layer serial. Protect existing resource modes and approval gates. This isolates workflow benefits from inference complexity.

**Stage 2: shared-resident inference experiment.** On a disposable environment and a single supported model, evaluate concurrent slots/batching, context growth and tail latency. Avoid adding an MoE backend until the effect of parallel requests is understood.

**Stage 3: dynamic task scheduling.** Build bounded task graphs (initially 1 to 3 workers), structured evidence contracts, cancellation and deterministic merges; support up to five only if benchmarks show value.

**Stage 4: streamed MoE as an optional backend.** Test verified compatible runtimes and a model that actually benefits the user's workloads. Keep the current resident specialists as fallbacks; do not couple the entire system to one experimental project.

Every stage must have a performance gate, safety regression gate, compatibility review and straightforward rollback to the stable release. The order can change if code evidence supports a better plan, but the justification must be explicit.

## 10. Expected Work output format and final decision

Produce one consolidated report containing:

- **Executive answer:** Is a substantial redesign justified now? What is the cheapest high-value change? What would be lost by switching to one common 35B model?
- **Verified repository map:** exact relevant paths, interfaces and source evidence; note discrepancies between docs and implementation.
- **As-is vs to-be diagrams:** separate task concurrency, model residency and token-level inference concurrency.
- **Use-case ranking:** ordinary conversation, this MiniCPM research exchange, full LOCAL AI code audit, document archive, document writing and multi-project development.
- **Decision matrix:** current serial system; tool-task concurrency; shared-model batching; streamed MoE; hybrid roles; separate instances. Include complexity, safety, storage, expected benefit and evidence quality.
- **Benchmark/experiment specification:** reproducible instructions, workload fixtures, metrics, failure gates and how to interpret contradictory results.
- **Proposed engineering plan:** stages, dependencies, affected files, tests, migration, rollback and unresolved questions. No code changes without separate approval.
- **Recommendation:** proceed, prototype only, or do not proceed, with clearly stated reasons and unknowns.

### Definition of a successful review

The report should make it possible to decide **whether parallel agents would do more *useful* work on this specific 32 GB / 256 GB Mac**, which parts of LOCAL AI genuinely need change, whether three agents capture most of the benefit, and whether SSD-streamed 35B inference is practical or a distraction. It must neither dismiss the idea because of outdated all-weights-in-RAM assumptions nor accept the mobile 3 GB figure as proof of a five-agent swarm.

## 11. Primary repository reading list

Start with the live `main` branch and trace imports/call sites as needed:

- [README.md](https://github.com/MisterDataScience/local-ai-environment-/blob/main/README.md)
- [docs/architecture/CONNECTED_SYSTEM_MAP.md](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/architecture/CONNECTED_SYSTEM_MAP.md)
- [docs/MODEL-TEAM-AND-HANDOFFS.md](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/MODEL-TEAM-AND-HANDOFFS.md)
- [docs/WORK-AGENT.md](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/WORK-AGENT.md)
- [docs/HANDOFF-IMPLEMENTATION-PLAN.md](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/HANDOFF-IMPLEMENTATION-PLAN.md)
- [docs/TEXT-MODELS-AND-IDLE.md](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/TEXT-MODELS-AND-IDLE.md)
- [docs/AUTONOMOUS-JOBS.md](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/AUTONOMOUS-JOBS.md)
- [docs/SCOPED-AUTOMATION.md](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/SCOPED-AUTOMATION.md)
- [installer/payload/model_engine.py](https://github.com/MisterDataScience/local-ai-environment-/blob/main/installer/payload/model_engine.py)
- [installer/payload/model_team.py](https://github.com/MisterDataScience/local-ai-environment-/blob/main/installer/payload/model_team.py)
- [installer/common.py](https://github.com/MisterDataScience/local-ai-environment-/blob/main/installer/common.py)

**Provenance:** Repository-specific facts above are drawn from the inspected `main` source and project documentation available in the preceding discussion. They are a starting point and require fresh validation by GPT Work. Runtime benchmark statements and MiniCPM memory claims are research leads, not acceptance-tested results on the owner's machine.
