# Orchestrator assessment

Assessment date: 2026-10-05. Based on the included source and primary project documentation. No Mac hardware execution was performed.

## What was selected

The selected orchestrator is the custom Python standard-library HTTP gateway at `installer/payload/gateway.py`. It is not SmarterRouter, llama-swap or FastAPI. Open WebUI connects to its OpenAI-compatible endpoint using the single exposed model ID `local-ai`.

## Actual implementation

| Requirement | Existing implementation | Classification / remaining work |
| --- | --- | --- |
| Text/media routing | Normal messages vs explicit `/image` and `/video` | Existing custom code; no natural-language selection |
| Multiple text models | One `text_model` setting | Static configuration possible; dynamic selection requires code |
| On-demand text loading | Ollama loads the requested model | Native backend behaviour |
| Text idle unloading | `/api/chat` sets `keep_alive: "5m"` | Native Ollama facility used by existing code |
| Explicit unloading | Enumerates `/api/ps`, sends `/api/generate` with `keep_alive: 0`, polls empty list | Existing custom coordination using native Ollama API |
| Sequential use | Single executor, unload before render, teardown before text | Existing custom code |
| ComfyUI release | Starts per render and terminates process group afterward | Existing custom process management |
| Global profile state | None | New code |
| Profile model/tool restrictions | None | New backend policy code |
| Gaming selector | None | UI integration and state transition code |
| Search/retrieval | None; tool calls rejected | New integration |
| Selective VPN | None | Container/network deployment and integration |
| Background startup | Foreground Terminal supervisor only | Background service deployment and supervisor changes |
| Guaranteed memory ceiling | None | Separate resource-control design and validation |

The five-minute keep-alive is hardcoded in requests. Changing `OLLAMA_KEEP_ALIVE` alone does not override it. Ollama documents that request-level keep_alive takes precedence. The gateway does not measure actual available unified memory. External clients calling the backend directly can bypass its coordination.

## Existing tools worth using

- **Open WebUI:** established chat UI with SearXNG search configuration, ComfyUI image integration, external web loader configuration and Python Functions. Reuse supported interfaces where practical. A custom Function remains custom code; supported extensibility does not mean Gaming policy exists already.
- **llama-swap:** established on-demand process swapping for compatible inference servers. Its maintainer describes ComfyUI integration as requiring a wrapper. It does not establish a ready-made solution to global Gaming restrictions plus VPN retrieval.
- **SmarterRouter:** documents Ollama discovery, text routing and memory awareness including Apple Silicon. Combined profile restrictions, media handoff and isolated retrieval were not verified as native features. Do not treat these as supported from the project description alone.
- **Gluetun and SearXNG:** candidates for the isolated network/search layer, separate from GPU model orchestration. Both search and page retrieval need the VPN path.

No evaluated project was verified to provide the complete requested appliance as a drop-in system. This is a bounded assessment, not an exhaustive claim about all available software.

## Design direction, not an implemented replacement

Keep the existing gateway as a prototype. Prefer established Open WebUI features for chat, search and image interaction. Keep any remaining custom layer narrow: global profile enforcement and backend memory handoff. Do not add llama-swap or another router simply to increase the component count. No replacement orchestrator is selected yet.

Natural-language media requests are possible using tools/routing, but the current gateway rejects tool calls and requires slash commands. Enabling Open WebUI's image integration directly without policy coordination could bypass the gateway's handoff and future Gaming restrictions.

Search isolation requires special care: Open WebUI distinguishes search from web loading. External loaders are supported, but version-specific behaviour must be tested. Configuration alone is not proof that all network traffic is isolated. Docker's VM overhead also means the earlier infrastructure-memory estimate cannot be accepted without measurement.

## Primary references

- [Ollama FAQ: lifecycle, concurrency and local-only mode](https://docs.ollama.com/faq)
- [Open WebUI SearXNG integration](https://docs.openwebui.com/features/chat-conversations/web-search/providers/searxng/)
- [Open WebUI environment configuration and external web loaders](https://docs.openwebui.com/reference/env-configuration/)
- [Open WebUI ComfyUI integration](https://docs.openwebui.com/features/chat-conversations/image-generation-and-editing/comfyui/)
- [Open WebUI Functions](https://docs.openwebui.com/features/extensibility/plugin/functions/)
- [llama-swap](https://github.com/mostlygeek/llama-swap)
- [llama-swap maintainer discussion of ComfyUI handoff](https://github.com/mostlygeek/llama-swap/discussions/962)
- [SmarterRouter](https://github.com/peva3/SmarterRouter)
- [Gluetun shared networking](https://github.com/qdm12/gluetun-wiki/blob/main/setup/connect-a-container-to-gluetun.md)
- [Gluetun firewall configuration](https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/firewall.md)
- [NordVPN's Gluetun/OpenVPN guide](https://support.nordvpn.com/hc/en-us/articles/47830508425745-How-to-set-up-an-OpenVPN-manual-connection-to-NordVPN-with-Gluetun)
