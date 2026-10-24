# LOCAL AI

A local AI system for a single-user Apple Silicon Mac. The Captain uses native
OpenCode sessions to coordinate bounded workers. Open WebUI provides ordinary
chat. The system includes Office/file tools, vision and PDF/OCR, image/video,
speech, an encrypted workspace and private Tailscale access. See
[deployment](docs/DEPLOYMENT.md) for installation and account requirements.

`main` is the source of truth. The checked-in
[installer ZIP](downloads/Mac-Local-AI-Automated-Installer.zip) is an older
snapshot and does not contain all current source changes. Source merges do not
refresh it automatically. The release workflow is manual-only and publishes a
replacement only after its Linux and two native macOS gates pass. See
[release validation](docs/RELEASE-VALIDATION.md) before choosing a package.

## Install or upgrade

Requirements: native Apple Silicon, macOS 15+, 32 GB unified memory and at least
100 GB free space for the initial install. Stop Local AI and the Work Agent
before upgrading. Existing configuration, credentials, models and chats are retained.

1. Obtain a validated installer for the intended source revision and extract it.
2. Open `Install Local AI.command` inside `mac-local-ai-installer` once.
3. Complete the Apple, Cryptomator, Docker, Proton VPN and Tailscale prompts
   described in [deployment](docs/DEPLOYMENT.md#installation-or-upgrade).
4. Review native acceptance results. After the required checks pass, the installer
   registers login startup and opens the authenticated Captain interface.

The standard 32 GB installation selects AtomicChat's abliterated MiniCPM-V 4.7
Captain profile with verified base weights, vision projector and mandatory LoRA.
Captain and temporary workers share model weights; the separate document model
remains available. See [model selection](docs/CAPTAIN-MODEL-SELECTION.md).

Use `Local AI.app` or `Open Captain.command` after installation. The local Captain
is at `http://127.0.0.1:4096`; ordinary chat is at `http://127.0.0.1:8081`.
Worker delegation takes place in the Captain Work Agent. Off-device access uses
the private Tailscale origin described in [remote access](docs/REMOTE-ACCESS.md).
Cryptomator vault unlocking remains an owner action after reboot.

## Use the system

| Task | Guide |
| --- | --- |
| Captain delegation, shared findings and worker retirement | [Captain and workers](docs/CAPTAIN-AND-WORKERS.md) |
| Personal knowledge, resident preparation and exact owner review | [Founding and recovery](docs/FOUNDING-AND-RECOVERY.md), [resident memory](docs/RESIDENT-MEMORY.md) |
| Studio Lead and the saved planning-to-playtest workflow | [Institutions and studios](docs/INSTITUTIONS-AND-STUDIOS.md) |
| Studio construction, repairs and institutional archives | [The Synod](docs/THE-SYNOD.md) |
| Finite social/creative sessions | [Village Commons](docs/VILLAGE-COMMONS.md) |
| Workshop, project notices and practice cases | [Village infrastructure](docs/VILLAGE-INFRASTRUCTURE.md) |
| DOCX, XLSX and PPTX | [Office tools](docs/OFFICE-TOOLS.md) |
| VPN search and browser | [Web access](docs/WEB-ACCESS.md), [browser](docs/BROWSER-MCP.md) |
| Explicitly authorised document batches | [Autonomous jobs](docs/AUTONOMOUS-JOBS.md) |
| Isolated desktop control and external reasoning | [Scoped automation](docs/SCOPED-AUTOMATION.md) |
| Resource budgets, compaction and workflow token reports | [Context management](docs/CONTEXT-MANAGEMENT.md) |

For personalisation, open `Village Commons.command` and select **Prepare the
Village from your conversation history**. The host prepares baseline residents
and cited proposals. Lasting knowledge, access and membership changes retain
their owner review. C studios keep one persistent game production lane per studio;
the Studio Lead manages saved department handoffs.

## Verification and limits

This is an installation candidate. Authoring tests do not establish owner-Mac
GPU performance, memory pressure, microphone quality, VPN-drop behaviour or
physical reboot/sleep recovery. See [release validation](docs/RELEASE-VALIDATION.md),
[first-install gaps](docs/PREINSTALL-FAILURE-AUDIT-2026-10-15.md) and
[headless/remote acceptance](docs/HEADLESS-AND-REMOTE-ACCEPTANCE.md).

The installer writes `captain-install-readiness.json` only after its required
native, workspace and live service checks pass. Review its unobserved physical
journeys and account-dependent services. Use `Check Required Capabilities.command`
and the dedicated feature checks for enabled capabilities.

Source checks, with the documented test dependencies installed:

```bash
PYTHONPATH=installer:installer/payload python3 -m unittest discover -s installer/tests -v
PYTHONPATH=installer:installer/payload python3 -m unittest discover -s installer/payload/tests -v
node --test $(find installer/tests -name '*.mjs' ! -name 'test_conversation_browser.mjs')
```

The optional conversation browser test also needs Playwright Chromium.
`python3 scripts/build_installer.py --check` checks an existing ZIP against source;
it does not rebuild it or run native acceptance. A stale archive must fail.
Packaged `RELEASE.json` records file hashes; historical input revisions alone do
not prove that a package matches the current source.

Feature branches and `manual-setup/` are development/history material. The
[manual setup guide](docs/Mac-Local-AI-Setup-Guide.md) describes the original
October 2026 baseline, not the current installer. Model weights, generated outputs
and credentials do not belong in this repository.
