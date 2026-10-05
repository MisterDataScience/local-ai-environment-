# Local AI project: updated requirements

Recorded 2026-10-05. Optional private Tailscale remote access has since been added; native validation remains pending. These are desired behaviours, not claims about the existing installer.

## Hardware and purpose

Target: a 32 GB unified-memory Apple Silicon Mac mini. Provide local text/reasoning/coding chat, images, video and controlled web search/retrieval from one chat interface. macOS, ordinary applications and games share the same memory pool. Cold-start latency and sequential model swapping are acceptable.

The user should not need to launch or configure Ollama, ComfyUI, Docker, search, VPN or the gateway during ordinary use. Initial account credentials and any required macOS permissions are separate setup requirements.

## Desired daily operation

1. After Mac startup/login, lightweight infrastructure starts automatically.
2. Heavy model weights remain unloaded until a request needs them.
3. The user opens one chat interface and explicitly selects Gaming, Normal or Max.
4. The active profile controls eligible models and tools.
5. Models load on demand, run inference and unload after an idle timeout.
6. Switching to a larger profile makes its models eligible without preloading them.

Infrastructure running does not mean model weights must remain resident. A persistent ComfyUI server is optional if process startup/teardown offers more reliable memory release and remains invisible to the user.

## Operating profiles

| Profile | Text | Search | Image/video | Resource policy |
| --- | --- | --- | --- | --- |
| Gaming | Small quantised model, approximately 2–4B class | Enabled through VPN | Both blocked | Short context, limited concurrency and short idle timeout; heavy models technically blocked |
| Normal | Better everyday model | Enabled through VPN | Images available; video eligibility to define | On-demand loading and sequential handoff |
| Max / Heavy | Largest sensible model validated on this Mac | Enabled through VPN | Both available | Full reasoning/coding access, sequential handoff |

Prefer explicit selection initially; automatic game detection is not required. Initial text presets now use Qwen3 4B, 14B and 30B-A3B, with 120/300/60-second idle timeouts. They are selectable text options, not enforced global profiles; budgets and native compatibility remain unmeasured. World of Warcraft is an example gaming workload, not a verified performance test.

Gaming Mode must enforce restrictions in backend code, not just a prompt or hidden menu option. Old chats, queued requests and tools must obey the active global profile.

When switching to Gaming:

1. Prevent admission of new heavy requests immediately.
2. Cancel or otherwise safely stop active heavy work according to an explicit policy.
3. Remove/reject queued heavy requests and prevent stale requests from starting later.
4. Stop/release ComfyUI and unload large Ollama models; confirm completion.
5. Permit only the approved tiny model, context and concurrency settings.
6. Keep VPN search available. Do not preload the tiny model merely because the profile changed.

A strict RAM ceiling is a separate technical requirement. Model size, context caps and admission checks constrain demand but do not provide a guaranteed operating-system memory limit. Measure actual usage and define failure/stop behaviour before making such a guarantee.

## Search privacy

Only AI search/retrieval should use NordVPN. Safari, Dropbox, games and ordinary Mac traffic keep their normal connection. The objective is to avoid exposing the home public IP to search providers and sites automatically visited by the AI; it is not absolute anonymity.

Proposed topology: local AI calls a local search/retrieval endpoint; its network traffic passes through Gluetun and NordVPN. Docker search and retrieval containers share the VPN service's network namespace using `network_mode: service:vpn` when the Compose service is named `vpn`. SearXNG is a candidate search engine.

Required properties:

- Search queries, page retrieval, redirects and DNS use the VPN route.
- No direct internet fallback if the VPN tunnel fails.
- Search fails visibly while the VPN is unavailable; local chat remains usable.
- A search container must not have a second ordinary internet network attachment.
- Host-side loaders, link previews or tool implementations must not fetch pages directly.
- VPN credentials stay outside source control.
- Initial software/model downloads are distinct from the runtime AI retrieval policy.
- Ideally local inference and orchestration have no arbitrary runtime internet access; enforce this separately where practical.

Routing SearXNG alone through the VPN is insufficient if Open WebUI or the gateway fetches result pages directly. DNS routing and failure behaviour need actual tests, including tunnel interruption and service restart.

## Memory lifecycle and budget

Text: load on a request, retain briefly, then unload after about five idle minutes. Use explicit Ollama unload before media or a profile transition. One heavyweight workload at a time. Media weights must release after use, with teardown confirmation before text resumes.

The earlier 0.5–1 GB infrastructure estimate is a target, not a measurement. Include Docker's Linux VM, Open WebUI, VPN, search and retrieval when measuring. The total must leave room for macOS, games, applications and inference buffers. A tiny model still uses CPU/GPU resources during inference.

## Required verification before an appliance claim

- Native model generation and memory release on the actual Mac.
- Gaming restrictions hold across chats, tools, API requests, queued jobs and profile transitions.
- Heavy work cannot start after Gaming activation.
- Normal/Max selection does not load models automatically.
- VPN tunnel failure blocks external search, retrieval and DNS without home-IP fallback.
- Non-AI Mac traffic retains the normal route.
- Startup, restart, sleep/wake and VPN-unavailable operation work without daily Terminal use.
- Infrastructure memory and gaming impact are measured.

## Scope of the next step

First inspect the already-selected orchestrator and compare established tools. Distinguish existing code, native backend capabilities, configuration and new custom code. Do not redesign the whole system or assume these features exist. The existing installer remains a prototype until an updated implementation passes these checks.

## Remote devices

Access the same chat, history, folders and generated outputs from iPad, phone and Windows through private Tailscale HTTPS. This installer option is implemented with one-time sign-in and extension approval. It does not route ordinary internet traffic through Proton or implement background AI startup. See REMOTE-ACCESS.md for scope and pending browser validation.
