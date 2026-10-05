# Local AI environment

Personal local AI project for a **32 GB unified-memory Apple Silicon Mac mini**. This project is separate from OTHM coursework.

**Status: prototype.** The included installer implements text, image and short video generation through a custom Python gateway. Unit/mock tests passed in the authoring environment. Native Mac installation, Apple GPU inference and memory use have not been verified here. The installer performs acceptance checks on the target Mac.

The updated Gaming/Normal/Max profiles, isolated VPN search and automatic background startup are **requirements, not implemented features**.

## Files

| Location | Contents |
| --- | --- |
| [installer/](installer/) | Automated installer, runtime supervisor, gateway, workflows and tests |
| [installer/README.md](installer/README.md) | Installation instructions and current limitations |
| [manual-setup/](manual-setup/) | Earlier manual setup source, retained for reference |
| [docs/Mac-Local-AI-Setup-Guide.md](docs/Mac-Local-AI-Setup-Guide.md) | Original detailed manual guide |
| [docs/PROJECT-REQUIREMENTS.md](docs/PROJECT-REQUIREMENTS.md) | Updated operating, privacy and resource requirements |
| [docs/ORCHESTRATOR-ASSESSMENT.md](docs/ORCHESTRATOR-ASSESSMENT.md) | Actual gateway capabilities and established-tool assessment |
| [downloads/](downloads/) | Existing installer and manual setup ZIP bundles |

## Current software choices

| Role | Choice |
| --- | --- |
| Chat interface | Open WebUI 0.11.1 in Safari |
| Text inference | Native Ollama, selectable Qwen3 4B / 14B / 30B-A3B |
| Image generation | Native ComfyUI v0.38.0 with SDXL Base 1.0 |
| Video generation | LTX-Video 2B v0.9.5 with T5 FP16, through ComfyUI |
| Orchestrator | Custom Python standard-library gateway, `installer/payload/gateway.py` |

Ordinary chat goes to Ollama. `/image DESCRIPTION` and `/video DESCRIPTION` trigger media generation. One job runs at a time. Before rendering, the gateway unloads Ollama and checks its loaded-model list; after rendering it stops ComfyUI before text can resume. Text uses configurable per-model idle timeouts: Small 2 minutes, Everyday 5 minutes and Large 1 minute. Selecting a model does not load it; the next request does. These are text presets, not global Gaming profiles. The current gateway rejects tool-calling and non-text attachments.

The current daily launcher starts services in Terminal and opens Safari. Terminal must remain open. This is not yet the background appliance described in the requirements.

Remote access is now available as an optional installer stage. See [private access from your other devices](docs/REMOTE-ACCESS.md). Tailscale sign-in and macOS extension approval remain interactive setup steps.

## Install the current prototype

Read [the installer instructions](installer/README.md) first. Download [Mac-Local-AI-Automated-Installer.zip](downloads/Mac-Local-AI-Automated-Installer.zip) using GitHub's file download control, extract it into Downloads and run:

```bash
/bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI.command"
```

This installs under `~/LocalAI-Automated`. Requirements: Apple Silicon, macOS 15+, at least 32 GB unified memory and 100 GB free disk for an initial installation. Large model downloads and generation acceptance tests are involved. This bundle does not install VPN/search or Gaming Mode.

## Authoring verification

```bash
python3 -m unittest discover -s installer/tests -v
python3 -m unittest discover -s installer/payload/tests -v
bash -n 'installer/Install Local AI.command'
```

The two suites contain 20 installer/remote-access tests and 18 gateway tests. They verify logic with mocks, not GPU execution. Native acceptance checks exercise every configured text model, then text, image, text, video and text with Open WebUI running; they do not automate all browser interactions.

See [text model and idle settings](docs/TEXT-MODELS-AND-IDLE.md) for model IDs, configuration and upgrade instructions.

## Next design decision

Assess established Open WebUI facilities and existing model managers before extending custom infrastructure. Keep any remaining policy/handoff code narrow. No replacement orchestrator has been selected and no updated implementation has been built.

Model weights, generated outputs, chat databases and runtime credentials do not belong in this repository. Downloadable ZIPs preserve the earlier prototype and do not imply the updated requirements are fulfilled.
