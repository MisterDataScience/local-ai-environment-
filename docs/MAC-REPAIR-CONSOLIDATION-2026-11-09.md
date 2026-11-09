# Mac installation and first-use repair consolidation

Release `2026-11-09-mac-native-recovery-1` integrates the repaired installer into
`main`, based on `a0e035c179cc14e520a6cb011b758262f4f5fa5f`. Existing Synod,
studios and optional integrations are retained. Unfinished Pixel Art work is
outside this change. Runtime/model pins and selected MiniCPM/LoRA weights are
unchanged. Hosted Actions remain manual-only under the existing budget rule.

| Failure | Integrated change |
| --- | --- |
| Core could depend on unfinished optional setup | Core-first modular installation, independent feature receipts and runtime capability gates |
| Thinking was disabled in stock profiles | Explicit thinking policy and one-time configuration migration |
| Reasoning ended without a final answer | MiniCPM reasoning/final-answer protocol reminder, including the structured-result path |
| Coder handoffs returned prose or malformed JSON | Native schema-bound StructuredOutput, with real submission identity checked |
| OpenCode rejected its format class during persistence or history encoding | Pinned Effect class-brand compatibility and a narrowly scoped read-only native SQLite history fallback |
| Inspection/test claims did not match execution | Actual native call IDs, completed inspection records and exact command/exit evidence; analysis remains a claim |
| Valid returns failed on optional analysis IDs or harmless commentary | Analysis-only ID omission allowed; native structured results remain authoritative; conflicting results still fail |
| Plan instructions blocked read-only dispatch/retirement | Exact pinned reminder replacement, retaining Build approvals and per-turn limits |
| Coder file tools failed under inherited permissions | Explicit read-only Plan coder profile and bound native identity checks |
| Managed startup could fail despite completed core work | Reserved project handling, checked launchers, stable local credentials and authenticated readiness checks |
| Streaming overflow became an endlessly retried generic server error | Native usage requested and context-length errors preserved in the SSE error envelope |
| A 16K Max context compacted too early | OpenCode generation cap of one quarter of context, up to 512 reserve tokens and bounded retained history |
| A completed chat resumed after compaction | Native completion-state guard and one resume per actual progress checkpoint |
| Requested output was mistaken for an answer already delivered | Original pending request restored verbatim from native history, with stale/completed resume authority rejected |
| Diagnosis repeatedly required full installation | Saved native diagnostics, scoped probes, backups and guarded repair paths |

For a 16K Captain, Normal and Max advertise input 12,288, generation 4,096 and
an additional compaction reserve of 512 tokens. The native trigger is 11,776.
Thinking and final text share the generation allowance. Open WebUI keeps its
separate compaction policy. Large individual inputs can still exceed context.

## Acceptance scope

The owner reported core installation and ordinary use working. The repaired
Mac installation then printed `Native conversation check: passed`. That probe
uses one new tool-denied session, two actual text replies and four forced
automatic compactions. It checks that completed replies stay finished and a
queued real request survives a misleading completion state.

The same check is now a required `native-captain-conversation` installation
gate, alongside native worker dispatch and retirement. It creates no success
receipt from model claims alone. The reusable checker can also inspect an
already running Captain through `Check Captain Conversation.command`.

Local Python/JavaScript tests and archive integrity checks are authoring
evidence. The pinned Linux OpenCode archive checksum was verified, but its
binary exits with SIGABRT before `--version` in this authoring environment.
That native executable check is blocked here. The rebuilt GitHub archive has
not itself been reinstalled on the Mac. Optional-feature, GPU-performance and
physical recovery acceptance are not inferred from the scoped Mac result.
