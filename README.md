# Local AI environment

Local speech and reference-voice cloning now use Qwen3-TTS 1.7B Base through
MLX-Audio. Use `/speak` or the coordinator's speech tool after registering a voice.
See [voice setup and limits](docs/VOICE-GENERATION.md).

The OpenCode coordinator can now request local images and videos through the
existing serial backend. Direct `/image` and `/video` commands remain available.
See [coordinator media and model review](docs/COORDINATOR-MEDIA.md).

Handoff reliability now includes immutable acceptance checklists, source-bound
quotes, native test-execution evidence and recoverable full reports. See
[work-agent contracts](docs/WORK-AGENT.md#acceptance-contracts).

Personal local AI project for a **32 GB unified-memory Apple Silicon Mac mini**. This project is separate from OTHM coursework.

**Status: prototype.** The included installer implements text, image and short video generation through a custom Python gateway. The previously established unit/mock suite passed in the authoring environment. New reverse-image unit/mock tests are included but have not been run by repository CI. Native Mac installation, Apple GPU inference and memory use have not been verified here. The installer performs acceptance checks on the target Mac.

Gaming/Normal/Max profiles are enforced through the gateway; use `AI Modes.command`. Automatic background AI startup remains unimplemented. Optional Proton VPN search, HTML page reading and opt-in Yandex reverse image search are implemented; native tunnel-drop/DNS and live reverse-search validation remain pending.

## Files

| Location | Contents |
| --- | --- |
| [installer/](installer/) | Automated installer, runtime supervisor, gateway, workflows and tests |
| [installer/README.md](installer/README.md) | Installation instructions and current limitations |
| [docs/GATEWAY-STRUCTURE.md](docs/GATEWAY-STRUCTURE.md) | Gateway modules and behaviour-preserving split |
| [manual-setup/](manual-setup/) | Earlier manual setup source, retained for reference |
| [docs/Mac-Local-AI-Setup-Guide.md](docs/Mac-Local-AI-Setup-Guide.md) | Original detailed manual guide |
| [docs/PROJECT-REQUIREMENTS.md](docs/PROJECT-REQUIREMENTS.md) | Updated operating, privacy and resource requirements |
| [docs/ORCHESTRATOR-ASSESSMENT.md](docs/ORCHESTRATOR-ASSESSMENT.md) | Actual gateway capabilities and established-tool assessment |
| [downloads/](downloads/) | Existing installer and manual setup ZIP bundles |

## Encrypted workspace update

Cryptomator is now included in the installer. Register an iCloud-backed vault
with `Configure AI Workspace.command`, manually unlock it, and enable the
workspace tools in Open WebUI. No vault password or recovery key is requested,
saved to Keychain, or passed to the model. GitHub has a separate connection helper.
See [the setup and exact limitations](docs/ENCRYPTED-WORKSPACE.md).

**Vault mode saves images and videos directly into the unlocked vault.**
Chat history/uploads run locally, with offline encrypted-vault backups before
startup and after clean shutdown. Backup, restore and legacy archive/media-copy
helpers are included. Native Mac verification remains required.

## Current software choices

The disabled bespoke GitHub adapter and approval lifecycle have been removed. GitHub can now be configured through the official remote MCP service with the Connect GitHub helper; live authentication and approval checks remain pending. See [GitHub integration](docs/GITHUB-INTEGRATION.md).

The gateway remains one process and owns model lifecycle work. Open WebUI owns the tool loop and approval interface. The gateway translates structured tool messages to/from Ollama without executing them. See [native tools and current limits](docs/NATIVE-TOOLS.md).

| Role | Choice |
| --- | --- |
| Chat interface | Open WebUI 0.11.1 in Safari |
| Text inference | Native Ollama 0.40+, Huihui Qwen3.5 4B / 9B and Gemma4 12B Coder (4-bit) |
| Image generation | Native ComfyUI v0.38.0 with SDXL Base 1.0 |
| Video generation | LTX-Video 2B v0.9.5 with T5 FP16, through ComfyUI |
| Orchestrator | Custom Python standard-library gateway, `installer/payload/gateway.py` |
| Web access | SearXNG + bounded reader, sharing Gluetun/Proton Free's network namespace; optional Yandex reverse image search uses Gluetun's loopback HTTP proxy |

Ordinary chat goes to Ollama. `/image DESCRIPTION` and `/video DESCRIPTION` trigger media generation. One job runs at a time. Before rendering, the gateway unloads Ollama and checks its loaded-model list; after rendering it stops ComfyUI before text can resume. Text uses configurable per-model idle timeouts: Small 2 minutes, Everyday 5 minutes and Large 1 minute. Selecting a model does not load it; the next request does. Global resource modes restrict which presets and media jobs are eligible. See [Resource modes](docs/RESOURCE-MODES.md). The gateway accepts function definitions and matching text tool results; it does not execute supplied functions. Image/audio inputs remain unsupported.

The current daily launcher starts services in Terminal and opens Safari. Terminal must remain open. This is not yet the background appliance described in the requirements. Native tool calls now pass through the gateway. VPN retrieval is available through a small authenticated OpenAPI bridge; enable that connection in the chat or attach it to a model. Media still uses explicit commands. End-to-end native WebUI tool selection and approval remain unverified on the Mac.

Remote access is now available as an optional installer stage. See [private access from your other devices](docs/REMOTE-ACCESS.md). Tailscale sign-in and macOS extension approval remain interactive setup steps.

Web access is optional: [setup, commands and privacy boundaries](docs/WEB-ACCESS.md). Use `/search QUERY` or `/read URL QUESTION`. Use `/reverse Inbox/photo.jpg` for explicitly invoked reverse image search after setup. Reverse image search is separately opt-in, uses images explicitly selected from the encrypted workspace, strips metadata into a derivative, and fails closed unless the installer-managed VPN proxy is available. These gateway paths have no direct-internet fallback. A local Docker engine and Proton WireGuard key require one-time setup. This does not block all native WebUI URL-loader/plugin traffic.

## Install the current prototype

Read [the installer instructions](installer/README.md) first. Download [Mac-Local-AI-Automated-Installer.zip](downloads/Mac-Local-AI-Automated-Installer.zip) using GitHub's file download control, extract it into Downloads and run:

```bash
/bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI.command"
```

This installs under `~/LocalAI-Automated`. Requirements: Apple Silicon, macOS 15+, at least 32 GB unified memory and 100 GB free disk for an initial installation. Large downloads and native acceptance tests are involved. Use `Install Local AI with Web Access.command` for VPN search after completing its prerequisites. Gaming Mode is included through `AI Modes.command`; wait for Ready before starting a game.

## Authoring verification

```bash
python3 -m unittest discover -s installer/tests -v
python3 -m unittest discover -s installer/payload/tests -v
node --test installer/tests/test_opencode_team.mjs
bash -n 'installer/Install Local AI.command'
```

The suites verify logic with mocks/local HTTP, not a real VPN or GPU. Native generation checks exercise every configured text model, then text, image, text, video and text with Open WebUI running. VPN-drop/DNS tests remain pending. See installer/VALIDATION.txt for authoring results.

See [text model and idle settings](docs/TEXT-MODELS-AND-IDLE.md) for model IDs, configuration and upgrade instructions.

## Next design decision

Keep remaining policy/handoff code narrow. No replacement orchestrator has been selected. Gluetun and SearXNG provide VPN/search; the custom reader and gateway connect them without host-side page fetching.

Model weights, generated outputs, chat databases and runtime credentials do not belong in this repository. The automated ZIP tracks the updated installer; the manual ZIP is historical. Neither implies all requirements are fulfilled or hardware-verified.

## Dedicated work harness

The installer includes upstream OpenCode. Use `Start Work Agent.command` in Normal
or Max for its native Plan/Build web interface, approval prompts and a separate
project copy. It uses the existing local gateway. Read [WORK-AGENT.md](docs/WORK-AGENT.md)
for local storage, permission boundaries and native acceptance checks. Open WebUI
Pyodide execution settings are now explicit; the pinned version already enabled
them by default.


## Output budgets for the 32 GB M6 target

Gaming retains 4K context and 1K output. Normal/Max use role contexts of 8K coordinator, 32K analyst/document and 16K coder with 4K/8K output ceilings, bounded to half the context. Smaller customised contexts reduce their output ceilings automatically. The gateway preserves Ollama length cutoffs in both JSON and SSE, and OpenCode advertises the active limits. The installer migrates stock contexts once and adds native cutoff checks. Actual M6 memory pressure and long-response performance remain unverified. See [context and output settings](docs/CONTEXT-MANAGEMENT.md).

The automated installer now applies mode-specific native compaction and rejects oversized text input through Ollama's own context enforcement. It reserves output/tool space in OpenCode and checks first messages, history and tool envelopes during Mac acceptance. [Context management and remaining limits](docs/CONTEXT-MANAGEMENT.md).

## OpenCode model team and handoffs

The agreed three-model team, routing rules, handoff contract and 32 GB memory policy are recorded in [MODEL-TEAM-AND-HANDOFFS.md](docs/MODEL-TEAM-AND-HANDOFFS.md). [HANDOFF-IMPLEMENTATION-PLAN.md](docs/HANDOFF-IMPLEMENTATION-PLAN.md) maps the work to current modules and orders implementation. The installer now configures the team in OpenCode, with persistent two-attempt budgets, depth-one delegation, an approval-controlled coding agent and direct `/code`, `/analyse` and `/document` commands. WebUI delegation remains planned. Native Mac inference and end-to-end OpenCode validation remain pending.
