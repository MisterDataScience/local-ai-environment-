# Local AI environment

Personal local AI project for a **32 GB unified-memory Apple Silicon Mac mini**. This project is separate from OTHM coursework.

**Status: prototype.** The included installer implements text, image and short video generation through a custom Python gateway. Unit/mock tests passed in the authoring environment. Native Mac installation, Apple GPU inference and memory use have not been verified here. The installer performs acceptance checks on the target Mac.

Gaming/Normal/Max profiles and automatic background AI startup remain unimplemented. Optional Proton VPN search and HTML page reading are implemented; native tunnel-drop/DNS validation remains pending.

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

## Current software choices

The gateway now has focused modules and a small `gateway.py` entry point. It remains one process. This split does not add tool calling or account connectors.

| Role | Choice |
| --- | --- |
| Chat interface | Open WebUI 0.11.1 in Safari |
| Text inference | Native Ollama, selectable Qwen3 4B / 14B / 30B-A3B |
| Image generation | Native ComfyUI v0.38.0 with SDXL Base 1.0 |
| Video generation | LTX-Video 2B v0.9.5 with T5 FP16, through ComfyUI |
| Orchestrator | Custom Python standard-library gateway, `installer/payload/gateway.py` |
| Web access | SearXNG + bounded reader, sharing Gluetun/Proton Free's network namespace |

Ordinary chat goes to Ollama. `/image DESCRIPTION` and `/video DESCRIPTION` trigger media generation. One job runs at a time. Before rendering, the gateway unloads Ollama and checks its loaded-model list; after rendering it stops ComfyUI before text can resume. Text uses configurable per-model idle timeouts: Small 2 minutes, Everyday 5 minutes and Large 1 minute. Selecting a model does not load it; the next request does. These are text presets, not global Gaming profiles. The current gateway rejects tool-calling and non-text attachments.

The current daily launcher starts services in Terminal and opens Safari. Terminal must remain open. This is not yet the background appliance described in the requirements.

Remote access is now available as an optional installer stage. See [private access from your other devices](docs/REMOTE-ACCESS.md). Tailscale sign-in and macOS extension approval remain interactive setup steps.

Web access is optional: [setup, commands and privacy boundaries](docs/WEB-ACCESS.md). Use `/search QUERY` or `/read URL QUESTION`. These gateway paths have no direct-internet fallback. A local Docker engine and Proton WireGuard key require one-time setup. This does not block all native WebUI URL-loader/plugin traffic.

## Install the current prototype

Read [the installer instructions](installer/README.md) first. Download [Mac-Local-AI-Automated-Installer.zip](downloads/Mac-Local-AI-Automated-Installer.zip) using GitHub's file download control, extract it into Downloads and run:

```bash
/bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI.command"
```

This installs under `~/LocalAI-Automated`. Requirements: Apple Silicon, macOS 15+, at least 32 GB unified memory and 100 GB free disk for an initial installation. Large downloads and native acceptance tests are involved. Use `Install Local AI with Web Access.command` for VPN search after completing its prerequisites. Gaming Mode is not included.

## Authoring verification

```bash
python3 -m unittest discover -s installer/tests -v
python3 -m unittest discover -s installer/payload/tests -v
bash -n 'installer/Install Local AI.command'
```

The suites verify logic with mocks/local HTTP, not a real VPN or GPU. Native generation checks exercise every configured text model, then text, image, text, video and text with Open WebUI running. VPN-drop/DNS tests remain pending. See installer/VALIDATION.txt for authoring results.

See [text model and idle settings](docs/TEXT-MODELS-AND-IDLE.md) for model IDs, configuration and upgrade instructions.

## Next design decision

Keep remaining policy/handoff code narrow. No replacement orchestrator has been selected. Gluetun and SearXNG provide VPN/search; the custom reader and gateway connect them without host-side page fetching.

Model weights, generated outputs, chat databases and runtime credentials do not belong in this repository. The automated ZIP tracks the updated installer; the manual ZIP is historical. Neither implies all requirements are fulfilled or hardware-verified.
