# Context management

Team update: the table below describes legacy 16K presets. The installed team uses
8K coordinator, 32K analyst/document and 16K coder profiles. OpenCode advertises
each profile separately. WebUI still has a conservative global compaction trigger:
with the default team it is 2,048 tokens in Normal/Max and 1,536 in Gaming. It does
not yet gain per-role long-context compaction. Use OpenCode's analyst/document
agents for larger text work; WebUI's dedicated adapter is deferred.


Updated 2026-10-07 for the intended 32 GB M6 Mac mini. Applies to the automated installer, not the legacy manual-setup snapshot. No native M6 benchmark has been performed here.

## Ownership and budgets

Open WebUI 0.11.1 owns chat summarisation. OpenCode 1.18.34 owns agent-session compaction and pruning. The gateway does not summarise, delete stored history or run an extra agent loop.

| Mode | Default context | Output ceiling | WebUI compaction trigger | Summary ceiling |
| --- | ---: | ---: | ---: | ---: |
| Gaming | 4,096 | 1,024 | 1,536 | 512 |
| Normal | 16,384 | 4,096 | 8,192 | 1,024 |
| Max | 16,384 | 8,192 | 6,144 | 1,024 |

Max compacts earlier than Normal to leave space for its longer replies. Smaller custom contexts reduce these budgets automatically. WebUI's global threshold uses the smallest eligible model's budget. A smaller per-chat threshold remains effective. Recent-message retention remains the native 20% setting; this is a message percentage, not a guaranteed token budget.

The supervisor applies and verifies compaction settings through WebUI's supported local API on startup and after mode changes. It checks every two seconds, reuses an in-memory single-user session, avoids proxies and redirects, and retries failed updates with a warning in the log. Startup fallback is the conservative Gaming threshold. A mode switch can briefly precede the settings update; native backend enforcement remains active throughout. No additional summary model loads: compaction uses the active model. Task-model max_tokens is set to the summary ceiling while other task parameters are retained.

OpenCode advertises input = context minus output, with an additional reserve of up to 2,048 tokens for instructions and tool work. This makes its native reserved budget effective; advertising context alone did not. Smaller contexts reduce the reserve. A mode transition stops the harness; restart it to refresh its advertised limits.

The Captain keeps a compact standing routing policy. Detailed essay and reverse-scaffolding instructions are selected by the host for the explicit workflow, rather than appended to every document request. The ordinary document profile loads neither workflow. Native permissions filter tool schemas by role: document specialists remain tool-free, Plan denies edits/writes/patches, and video is hidden outside Max. The independent execution hooks retain their checks even when a tool schema is absent. Prompt character counts measure configuration size, not token usage or model quality.

Team board and inbox reads default to saved progress for that reader and explicit user turn. They share message progress, so reading a message on one does not repeat it on the other. Pages contain at most 12 events (eight by default). `has_more` signals further pages; omit `after` to continue saved progress or supply the returned `next_cursor` to page explicitly. `after=0` replays preserved records after context loss or uncertain delivery without rewinding saved progress. Board task previews are bounded, while `task_id` and saved report paths retain access to detail. Cursors survive a restart; old ledgers gain sequence numbers without losing their records. These are reads, not peer-wait polling loops.

Native specialist returns include a bounded review brief with acceptance evidence, test execution status and changed paths. The Captain reviews that brief directly when it is complete. `full_report_required` and `report_read_reasons` require a saved report read for clipped fields or unresolved review. Disputed or unclear evidence also requires the detail even if the flag is false. The full source contract, result and native records remain in the saved report. The combined brief falls back to a smaller explicit omission notice if its preview exceeds 8,000 UTF-8 bytes; this is a size bound, not a tokenizer estimate. Studio packets already use bounded navigation, evidence summaries and saved-result paging with scoped detail reads.

The gateway honours positive integer max_tokens and max_completion_tokens, using the lower if both are supplied. Output is additionally bounded to half the effective context. These are ceilings, not minimum answer lengths. Legacy/custom contexts remain at most 16K. Validated team profiles allow 8K coordinator, 32K analyst/document and 16K coder; Gaming remains at most 4K. The installer migrates recognised stock contexts once and preserves custom models, contexts, timeouts and credentials. One model still runs at a time with the existing unload policy. No GPU memory-safeguard override was introduced.

## Native input protection

The private Ollama backend must be version 0.40.0 or newer. The installer reuses a compatible private copy or downloads the official pinned 0.40.0 macOS archive with SHA-256 and code-signature verification. It verifies the candidate CLI before replacing the private app and preserves the previous app as tools/Ollama.app.before-context-TIMESTAMP. Models and chat data are retained. The gateway independently checks the running backend version before opening its listeners.

Every text request sets Ollama's native truncate=false and shift=false. Client attempts to override these flags are ignored. The backend's tokenizer and chat template enforce its context boundary, including history and tool envelopes. It cannot silently trim old messages or shift away input during generation. There is no approximate character estimator presented as an exact tokenizer, duplicate preflight inference, automatic input chunking or gateway retry.

Recognised explicit Ollama /api/chat HTTP 400/413 context errors become HTTP 400 with error.code=context_length_exceeded and a practical recovery message. Other backend failures remain HTTP 502 backend_error. JSON errors contain no successful assistant answer. After SSE headers are sent, errors appear as data events followed by DONE; HTTP status is already 200. Client willingness to compact and retry remains client-dependent.

Ollama's prompt_eval_count and eval_count become OpenAI usage fields in JSON and the final SSE chunk. done_reason=length becomes finish_reason=length. Partial text is preserved without inserting warning prose or automatically continuing the answer. Completed tool calls remain tool_calls unless the backend reports a length cutoff. Token counts alone are not treated as proof of cutoff.

## Remaining limits

Summaries are lossy. Important facts can disappear from the model's working context even though the stored original chat remains available. This is context reduction, not perfect persistent memory.

WebUI saved-chat compaction can fall back to full history if summarisation fails; unsaved chats and some other paths can bypass the hook. Large first messages, new pastes, tool definitions and tool results can exceed the context even before a history threshold is reached. Native enforcement now rejects those requests visibly. A document still needs splitting or retrieval if it cannot fit; the gateway does not do that automatically.

Thresholds are client hints, not exact complete-request counts. Output limits and native context enforcement also do not establish a hard RAM bound for every model. A 16K context is a bounded starting configuration, not a measured guarantee for every workload on the 32 GB Mac.

## Verification

Local tests exercise loopback JSON/SSE usage, cutoff and context-error delivery with mocked inference, immutable native safety flags, mode budgets, custom contexts, API authentication and media isolation. Loopback tests for the settings client verify mode changes, retained parameters, failed-update retries, authentication and redirect refusal. These tests do not execute the native clients or Apple GPU inference.

The Mac installer now verifies the native WebUI settings API and requests four deliberate context overflows from every configured text preset: a first message, old history, a tool result and a tool definition. Each must return the specific context_length_exceeded error; a successful answer or generic failure fails acceptance. Each preset also receives an eight-token cutoff test requiring finish_reason=length. Updated gateway code invalidates earlier hardware acceptance.

On the Mac, rerun the full updated installer with services stopped. Then check saved WebUI and OpenCode sessions compact and continue, including tool exchanges, in all modes. Check Gaming never loads a larger model for summarisation and that both clients display or recover from context errors and cutoffs. Test long essays in Normal and Max with normal background apps and the optional Docker stack running. Monitor memory pressure, swap and latency. If pressure is sustained, reduce the preset num_ctx to 8192 or 4096 and rerun acceptance; budgets shrink automatically. Do not disable Apple/PyTorch memory safeguards.

## Pinned upstream evidence

- https://github.com/ollama/ollama/blob/v0.40.0/api/types.go
- https://github.com/ollama/ollama/blob/v0.40.0/server/routes.go
- https://github.com/ollama/ollama/blob/v0.40.0/llm/llama_server.go
- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/utils/context_compaction.py
- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/routers/configs.py
- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/routers/auths.py
- https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/session/overflow.ts
