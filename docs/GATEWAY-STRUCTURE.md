# Gateway structure

The gateway remains one Python process. Native OpenCode owns the Captain/worker
tool loop and approvals; Open WebUI owns its ordinary chat tool loop. The gateway
translates individual inference requests without a replacement client tool loop.

| Module | Responsibility |
| --- | --- |
| gateway.py | Configuration, process lock, loopback listeners and shutdown |
| http_api.py | Authentication, OpenAI responses, tool-call SSE and media-only listener |
| model_engine.py | Bounded admissions, compatible text slots, inference/unload and ComfyUI lifecycle |
| inference_scheduler.py | Shared compatible text leases and exclusive model transitions |
| shared_llama.py | Verified shared llama.cpp process, completion and backend usage translation |
| backend_http.py | Backend JSON requests and loopback checks |
| routing.py | Text validation and explicit command routing |
| tool_protocol.py | OpenAI/Ollama tool schema/message conversion; no execution |
| token_stream.py | Bounded incremental Ollama text delivery and cooperative cancellation |
| conversation_audio.py | Resident audio workers, lease expiry, shared coordinator/exclusive heavy-model ownership |
| conversation_worker.py | Private Silero CPU, Parakeet MLX and Qwen3-TTS MLX workers |
| workflows.py | Workflow substitution and saved-output discovery |
| context_policy.py | Compaction budgets, required backend version and fixed-label usage rollups |
| text_models.py | Text preset validation and migration |
| web_client.py | Fixed-loopback VPN retrieval, evidence and citations |
| web_tools_api.py | Authenticated OpenAPI VPN bridge called by Open WebUI |

Without Captain, the executor has one worker. Captain enables a bounded executor
and compatible text requests may share the configured model slots. Gaming or an
enabled audio profile reduces text slots to one. Model preparation is locked;
incompatible profiles and heavy media use exclusive leases. Each inference call
is a job; a whole client tool session does not hold a lease while awaiting approval.
Conversation STT/TTS may overlap only the small coordinator profile under the
audio memory gate. Heavy jobs first release speech workers. Direct backend
clients can still bypass coordination.

`conversation.py` provides a separate loopback UI bridge to native OpenCode,
including scoped permission replies. It does not implement a replacement agent
loop. See [REALTIME-CONVERSATION.md](REALTIME-CONVERSATION.md).

runtime.py supervises Ollama, gateway and WebUI. ComfyUI starts only for a render.
remote_access.py handles private Tailscale access. web_access.py configures the
VPN/search containers and web/service.py performs isolated retrieval.

The installer manifest includes every current runtime module and fingerprints
them for native acceptance. Upgrades remove only explicitly named retired modules
and tests; models, chats, secrets and workflows are preserved. Rerun the full
installer with Local AI stopped, rather than replacing only gateway.py.

See [NATIVE-TOOLS.md](NATIVE-TOOLS.md) for protocol support, configuration and
remaining native/browser checks. The manual-setup directory is historical.


The authenticated local `/control/context` endpoint exposes budgets to runtime.py.
`context_settings.py` applies and verifies them through the native WebUI settings
API. Text inference disables Ollama input truncation and context shifting.
`/control/usage` reports cumulative workflow counts, with backend measurements,
estimates and unknown coverage kept separate. Both endpoints are unavailable on
the media listener. See [context management](CONTEXT-MANAGEMENT.md).
