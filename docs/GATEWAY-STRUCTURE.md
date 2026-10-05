# Gateway structure

Refactored 2026-10-05. A behaviour-preserving split, not a new orchestrator or tool-calling implementation. The launcher still runs `gateway.py` as one process. No new service, dependency, port or credential is required.

| Module | Responsibility |
| --- | --- |
| `gateway.py` | Entry point: configuration, process lock, loopback listeners, signals and shutdown |
| `http_api.py` | Authentication, OpenAI-compatible responses, SSE keepalives and media-only listener |
| `model_engine.py` | Single serial queue, Ollama inference/unloading, ComfyUI lifecycle/rendering and memory handoffs |
| `backend_http.py` | Backend JSON requests and loopback port checks |
| `routing.py` | Message validation and explicit command routing, without network calls |
| `workflows.py` | Workflow prompt/seed substitution and saved-output discovery |
| `text_models.py` | Text-preset configuration, validation and migration |
| `web_client.py` | Fixed-loopback retrieval, bounded evidence and source links |

`model_engine.py` deliberately retains ownership of both text and media lifecycle operations. They share one serial executor and state, preserving the handoff invariant. Python modules are not separate running services.

## Other components

`runtime.py` supervises Ollama, the gateway and Open WebUI. ComfyUI is started by the engine only when needed. `remote_access.py` handles Tailscale setup. `web_access.py` configures VPN/search containers; their reader stays in `web/service.py`.

## Behaviour unchanged

- Ordinary messages use the selected preset. `/image`, `/video`, `/search` and `/read` remain explicit commands.
- One model job runs at a time, with four admitted active/queued requests at most.
- Ollama unloading is confirmed before rendering; ComfyUI teardown completes before subsequent model work.
- Authentication, IDs, ports, response shapes, media URLs and idle timeouts are unchanged.
- Tool calls and non-text attachments remain rejected. GitHub/Dropbox connectors, repeated tool loops, Gaming policy and write approvals are not added.
- VPN retrieval boundaries and pending native checks remain unchanged.

## Installation and upgrade

The installer uses an explicit `GATEWAY_FILES` manifest and copies all modules into `~/LocalAI-Automated/control`. Every module contributes to the acceptance fingerprint. Tests verify manifest completeness and that changing any module invalidates native acceptance.

Run the updated installer with Local AI stopped. Chats, credentials, models, presets and edited workflows are preserved. Downloads are reused; native generation acceptance may rerun because code changed. Do not replace only `gateway.py`: neighbouring modules are required.

## Verification

Existing tests target their new owning modules. Additional checks cover manifest completeness, fingerprint invalidation and entry-point wiring/cleanup. The extracted ZIP is independently checked for imports and tests. Native Apple GPU and live VPN execution remain unverified here.

Future tool execution, account connectors and permission policy should use dedicated modules. No placeholder implementation is presented as working functionality.
