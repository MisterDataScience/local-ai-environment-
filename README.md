# LOCAL AI

A local AI system for a single-user Apple Silicon Mac. The Captain uses native
OpenCode sessions to coordinate bounded workers. Open WebUI provides ordinary
chat. The system includes Office/file tools, vision and PDF/OCR, image/video,
speech, an encrypted workspace and private Tailscale access. See
[deployment](docs/DEPLOYMENT.md) for installation and account requirements.

`main` contains the installer source and its matching
[downloadable ZIP](downloads/Mac-Local-AI-Automated-Installer.zip). Release
`2026-11-09-mac-native-recovery-1` brings the Mac installation and first-use
repairs back into the repository. The owner reported the repaired installation
working and its native conversation check passed. The rebuilt archive still
needs its own installation acceptance. See the [repair record](docs/MAC-REPAIR-CONSOLIDATION-2026-11-09.md)
and [release checks](docs/RELEASE-VALIDATION.md).

## Install or upgrade

Core needs native Apple Silicon, macOS 15+, 32 GB unified memory, Apple Command
Line Tools and 35 GB free space. Stop Local AI before upgrading. Keep your
existing installation, models and cached downloads.

1. Download and extract the installer ZIP.
2. In a Terminal window showing a shell prompt, run the core launcher:

   ```bash
   /bin/bash "$HOME/Downloads/mac-local-ai-installer/Install LOCAL AI Core.command"
   ```

   Adjust the folder if you extracted it elsewhere. A Terminal window occupied
   by `runtime.py` is running Local AI and cannot execute another shell command.
3. Let the installer finish its native checks. Core includes Captain and ordinary
   chat, with thinking enabled. It needs no optional account, vault or recording.
4. Add speech, media, encrypted storage, Office, web/browser or remote access
   later through the named installers. [Modular setup](docs/MODULAR-INSTALLER.md)
   lists each feature's requirements and checks.

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

After encrypted workspace acceptance, open `Village Commons.command` and select **Prepare the
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
native core and live service checks pass. Review its unobserved physical
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
