# Context management

Implemented 2026-10-06; output budgets updated 2026-10-07 for the intended 32 GB M6 Mac mini. Applies to the automated installer, not the legacy manual-setup snapshot. No native M6 benchmark has been performed here.

## Ownership

Open WebUI 0.11.1 owns chat summarisation. OpenCode 1.18.34 owns its agent-session compaction and pruning. The gateway does not summarise, delete history, or run an extra agent loop.

The installer enables Open WebUI's native compaction with a shared threshold and cap of 1,536 tokens and 20% recent-message retention. This conservative global setting accommodates Gaming's 4,096-token context. Default presets now use 16,384 tokens outside Gaming, so they compact earlier than necessary. The percentage is a native message-retention setting, not a guaranteed token budget. Compaction uses the active model; no larger summary model is selected behind Gaming mode's back. Model-specific compaction tuning is deferred.

OpenCode already has auto compaction and pruning enabled. Its configured context and output limits match the selected gateway mode and preset when launched. A mode transition stops the harness; restart it after the transition to refresh its advertised limits. No second compaction system was added.

The gateway honours positive integer max_tokens and max_completion_tokens requests, using the lower value if both are supplied. Invalid values fail before model loading. Short summary requests remain short. Caps are ceilings, not minimum answer lengths:

| Mode | Default context | Output ceiling |
| --- | ---: | ---: |
| Gaming | 4,096 | 1,024 |
| Normal | 16,384 | 4,096 |
| Max | 16,384 | 8,192 |

Output is additionally capped at half the preset's effective context. Preserved custom 4K contexts therefore allow at most 2,048 output tokens outside Gaming. This leaves space for input but is not a full-request token count or protection against oversized prompts. The validator permits contexts up to 16,384; client requests cannot override them. One model still runs at a time, with the existing unload/idle policy. No memory-safeguard override or extra model concurrency is introduced.

The installer migrates the three recognised stock model/context pairs once to 16K, preserving custom model tags, other context values, credentials, timeouts and workflows. It saves the pre-migration configuration privately as config.before-text-context-v2.json. Later reductions are preserved. Changed code/config invalidates previous hardware acceptance.

## Errors and usage

Ollama prompt_eval_count and eval_count are returned as OpenAI usage fields in JSON responses and the final SSE completion chunk. A backend failure produces an error object, never an apparently successful assistant answer containing an error message. After streaming headers are sent, failures are reported as SSE data events followed by DONE; HTTP status is necessarily already 200. Non-stream failures use HTTP 502, or HTTP 400 for recognised explicit context overflow.

Ollama done_reason=length now becomes finish_reason=length in both JSON and the final SSE chunk. Normal completion remains stop; completed function calls remain tool_calls unless the backend reports a length cutoff. Partial answer text and usage are preserved, without adding warning prose to the generated answer or automatically continuing it. Client presentation of the cutoff remains client-dependent. Older backends without a completion reason cannot establish cutoff reliably; token counts alone are not treated as proof. Native acceptance deliberately requests an eight-token essay from every preset and requires the length signal.

Recognised explicit context-rejection messages from Ollama /api/chat HTTP 400/413 are mapped to context_length_exceeded. Unrecognised backend errors remain backend_error. No automatic retry is performed by the gateway. A client's willingness to compact and retry is still client-dependent.

## Limits, not guarantees

- Open WebUI's native compaction can fall back to the full history when summarisation fails. Some chat paths, including unsaved chats, may bypass its saved-chat compaction hook.
- The threshold is not a complete preflight token count. Tool definitions, a large new paste, and oversized tool results can still overflow the context.
- No approximate character-to-token estimator was installed as if it were an exact safety boundary. A reliable full-request budget check needs model/tokenizer and chat-template validation, including tool schemas, before it can be enforced safely.
- A backend that silently truncates rather than returning an error will not be detected by error mapping. The actual installed Ollama version must be tested.
- Summaries are lossy. This is context reduction, not perfect persistent memory.
- Existing OpenCode files and storage boundaries are unchanged.

## Verification

Local automated tests exercise real loopback HTTP JSON and SSE responses with mocked inference: actual usage-field delivery, generic backend failure, explicit overflow, and absence of successful assistant chunks on error. Tests also cover output caps and the installer's native compaction configuration. These tests do not execute Open WebUI, OpenCode or Apple GPU inference.

On the Mac, before relying on long sessions:

1. Run the updated installer and restart Local AI.
2. Check a saved WebUI conversation compacts, retains recent instructions, and continues successfully on Small and Everyday. Include a tool exchange. Confirm Gaming does not load a larger model during summarisation.
3. In OpenCode, verify reported usage, native compaction and continuation through the gateway. Test an explicit oversized request and check whether the client recovers or shows the structured error.
4. Test a large first message and a large tool result separately. Do not assume either is protected by history compaction.
5. On the 32 GB Mac, test a long essay in Normal and Max separately on each eligible model, with WebUI and the optional Docker stack running. Monitor Activity Monitor memory pressure, swap growth and latency. 16K is a bounded starting configuration, not a measured guarantee that every model/workload fits. If a preset causes sustained pressure, reduce its num_ctx to 8192 or 4096, then rerun acceptance; its output ceiling reduces automatically. Do not disable Apple/PyTorch memory safeguards. Check Gaming still uses at most 4K/1K and releases larger weights before Ready.
6. Confirm the eight-token acceptance response reports length, and check WebUI/OpenCode actually expose or handle cutoff. The short installer test does not establish long-essay quality, maximum-length speed or a full-request memory budget.

## Pinned upstream evidence

- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/utils/context_compaction.py
- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/utils/middleware.py
- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/config.py
- https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/session/overflow.ts
- https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/session/compaction.ts

