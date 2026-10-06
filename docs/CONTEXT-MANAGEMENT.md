# Context management

Implemented 2026-10-06. Applies to the automated installer, not the legacy manual-setup snapshot.

## Ownership

Open WebUI 0.11.1 owns chat summarisation. OpenCode 1.18.34 owns its agent-session compaction and pruning. The gateway does not summarise, delete history, or run an extra agent loop.

The installer enables Open WebUI's native compaction with a shared threshold and cap of 1,536 tokens and 20% recent-message retention. This conservative global setting accommodates the 4,096-token Small and Large presets as well as the 8,192-token Everyday preset. The percentage is a native message-retention setting, not a guaranteed token budget. Compaction uses the active model; no larger summary model is selected behind Gaming mode's back. The 8K model therefore compacts earlier than strictly necessary. Model-specific tuning is deferred.

OpenCode already has auto compaction and pruning enabled. Its configured context limits match the gateway presets and its advertised output ceiling is 2,048. No second compaction system was added.

The gateway now honours positive integer max_tokens and max_completion_tokens requests, using the lower value if both are supplied, and clamps output to 2,048 tokens (1,024 in Gaming). This allows WebUI's short summary requests to remain short. Invalid values fail before model loading. Existing context sizes and memory policies are unchanged.

## Errors and usage

Ollama prompt_eval_count and eval_count are returned as OpenAI usage fields in JSON responses and the final SSE completion chunk. A backend failure produces an error object, never an apparently successful assistant answer containing an error message. After streaming headers are sent, failures are reported as SSE data events followed by DONE; HTTP status is necessarily already 200. Non-stream failures use HTTP 502, or HTTP 400 for recognised explicit context overflow.

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
5. Check summary quality and memory pressure before raising contexts or tuning thresholds.

## Pinned upstream evidence

- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/utils/context_compaction.py
- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/utils/middleware.py
- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/config.py
- https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/session/overflow.ts
- https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/session/compaction.ts
