# LOCAL AI installer

The Work Agent includes a captain and up to five temporary workers. The **Install Local AI.command** launcher automatically installs the chosen
MiniCPM Captain profile. The older named MiniCPM launcher is an alias, not an
extra step.
See [the captain explanation](docs/CAPTAIN-AND-WORKERS.md).

This is the single integrated installer for LOCAL AI. It includes vision,
Apple PDF/OCR, approved file workflows, background operation, the scoped Mac
controller and generic external reasoning, alongside the existing text,
Office, media and voice tools.

## Run

Stop LOCAL AI and the Work Agent before upgrading. On a native Apple Silicon
Mac with macOS 15+, 32 GB unified memory and at least 100 GB free space, run:

```bash
/bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI.command"
```

Use the downloaded folder's actual location if it differs. Keep Terminal open
while the installer downloads dependencies/models and performs native acceptance.
Installation lives under `~/LocalAI-Automated`. Existing local configuration and
credentials are retained. No credentials or model weights are packaged here.

## First-run Captain

During installation, Cryptomator opens so the owner can create or unlock the
vault inside the application. The installer detects a confirmed mounted volume,
registers the workspace and verifies protected reads and writes. A separate
`Configure AI Workspace.command` step is not needed. No passwords or recovery
keys are collected by LOCAL AI, and future vault unlocking remains manual.

After native tests pass, the installer registers the unprivileged login
LaunchAgent, starts the managed Captain Work Agent and opens
http://127.0.0.1:4096 in Safari. The installer prints the local-only
username and password. `Open Captain.command` prints them again if needed.
The Captain UI is separate from ordinary Open WebUI chat at
http://127.0.0.1:8081: delegation requires the Captain UI.

Core readiness is recorded at `~/LocalAI-Automated/captain-install-readiness.json`.
Physical reboot/permission/performance checks and account-bound integrations
are never silently marked as passed. The receipt records the vault installation
check and explicitly identifies the future manual-unlock requirement.

## Daily use

Launch `~/LocalAI-Automated/Start Local AI.command` or `Local AI.app`.
Captain installation registers the background startup automatically.
`Enable Login Startup.command` remains for manual repair or other profiles.
`Create Autonomous Job.command` authorises a finite local text-file batch with
crash-safe checkpoints and create-only Markdown output. `Autonomous Job Status.command`,
`Stop Autonomous Job.command JOB_ID`, and `Resume Autonomous Job.command JOB_ID`
manage its independent launchd worker. See docs/AUTONOMOUS-JOBS.md.
This does not authorise unrestricted unattended OpenCode tools.
`Stop Local AI.command` requests graceful shutdown. The chat is local at
`http://127.0.0.1:8081`; use the optional private remote-access setup for other devices.

Every capability's code is included. The following account-, permission- or
policy-bound services cannot be activated without local consent or credentials:

- Vision/PDF: chat uploads and Work Agent project tools; run `Check Required Capabilities.command`.
- Office/files: installed automatically; encrypted vault registration and smoke
  testing occur during Captain installation. Manual future unlocks and native
  transfer approvals remain required.
- Recurring text tasks: `Schedule AI Task.command`, then inspect `Scheduled Task Status.command`.
- VPN/browser: `Enable Web Access.command`, then `Enable Browser.command` and its check.
- Desktop: `Enable Desktop Control.command` and `Check Desktop Control.command`.
- Generic external helper: `Enable External Delegation.command`, with authorised provider access and verified selectors.

Scoped automation disables normal effectful chat/Work Agent tools while enabled.
Run `Disable Scoped Automation.command` and restart to return to normal workflows.
`Stop Automation.command` latches a stop; only local rearm permits a new session.

## Validation and guides

The ZIP contains `docs/DEPLOYMENT.md`, `docs/RELEASE-VALIDATION.md` and the individual
feature guides. In the source repository, these are in the top-level `docs` folder.
`RELEASE.json` in the ZIP records per-file hashes and the release identifier.

The combined source passes authoring tests. Owner-Mac GPU/memory, microphone,
VPN-drop, live browser/provider and native approval checks remain explicitly
unverified until run on that machine. Installer acceptance results and dedicated
check helpers report actual outcomes; do not infer success from a downloaded ZIP.

The canonical source and deployment package are on `main` at
https://github.com/MisterDataScience/local-ai-environment- . No feature branch is
needed for deployment. Historical manual setup files are not the current installer.
