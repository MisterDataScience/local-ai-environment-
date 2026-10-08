# Gateway structure

The gateway remains one Python process. Open WebUI now owns the tool loop and
approval interface; the former private loop and disabled GitHub adapter are removed.

| Module | Responsibility |
| --- | --- |
| gateway.py | Configuration, process lock, loopback listeners and shutdown |
| http_api.py | Authentication, OpenAI responses, tool-call SSE and media-only listener |
| model_engine.py | Serial model queue, Ollama inference/unload, ComfyUI lifecycle |
| backend_http.py | Backend JSON requests and loopback checks |
| routing.py | Text validation and explicit command routing |
| tool_protocol.py | OpenAI/Ollama tool schema/message conversion; no execution |
| token_stream.py | Bounded incremental Ollama text delivery and cooperative cancellation |
| conversation_audio.py | Resident audio workers, lease expiry, shared coordinator/exclusive heavy-model ownership |
| conversation_worker.py | Private Silero CPU, Parakeet MLX and Qwen3-TTS MLX workers |
| workflows.py | Workflow substitution and saved-output discovery |
| context_policy.py | Mode-specific compaction budgets and required backend version |
| text_models.py | Text preset validation and migration |
| web_client.py | Fixed-loopback VPN retrieval, evidence and citations |
| web_tools_api.py | Authenticated OpenAPI VPN bridge called by Open WebUI |

Text/media lifecycle operations still share one serial executor. Each inference call
is a job; a whole Open WebUI tool session no longer occupies the executor while
awaiting approval. Conversation STT/TTS may overlap only the small coordinator
profile, under a shared/exclusive memory gate. Heavy jobs first release speech
workers. Direct backend clients can still bypass coordination.

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


The authenticated local /control/context endpoint exposes budgets to runtime.py. It is unavailable on the media listener. context_settings.py applies and verifies those budgets through the native WebUI settings API. Text inference disables Ollama input truncation and context shifting.
