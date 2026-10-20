# LOCAL AI

The integrated [institutions and studio workbench](docs/INSTITUTIONS-AND-STUDIOS.md) adds private studios, a Lead Designer, source-based founding, approved memory maps and portable C computers at **320 × 180**. Open `Village Institutions.command` after updating the main installer.

One installer now combines the pending hardening and Village work. For first use,
open `Village Commons.command` and select **Prepare the Village from your
conversation history**. The system prepares the knowledge and agents; you approve
lasting changes. [Founding, encrypted recovery and source forgetting](docs/FOUNDING-AND-RECOVERY.md).

The host creates the five baseline residents automatically. The Captain can prepare complete specialist changes, and approved work prepares memory-map suggestions for owner review. [Normal use](docs/RESIDENT-MEMORY.md#normal-use-the-system-prepares-you-approve) requires no manual agent or map setup.

Residents now use an [owner-curated starting map](docs/RESIDENT-MEMORY.md): fast-access memories, a glossary of deeper own memories, and preferred Library or Archive workflows. The owner previews and approves map changes separately from approving memories or documents.

The optional [Village Commons](docs/VILLAGE-COMMONS.md) adds finite social and creative sessions, four active residents, owner-visible private drafts, and separately approved personal memories. Open `Village Commons.command` after installing; the guide includes a five-minute first session.

One source of truth: **`main`**. One deployment package:
[Mac-Local-AI-Automated-Installer.zip](downloads/Mac-Local-AI-Automated-Installer.zip).
Feature branches are development history, not installation choices.

The Work Agent now has a **captain and temporary workers**. One request can become
up to five independent workers with separate contexts, role-specific tools,
shared findings and peer messages. Compatible text requests can run concurrently
against one model; speech and media still use exclusive model handoffs.
Read [how the captain works](docs/CAPTAIN-AND-WORKERS.md).

The [Agent Village](docs/AGENT-VILLAGE.md) preserves raw history privately and can
[prepare the Village from your conversations](docs/FOUNDING-AND-RECOVERY.md).
Founding review, scoped Library knowledge, individual memories, automatic resident
proposals, encrypted recovery and reviewed managed-source erasure are implemented.
Native Mac acceptance remains unverified on the authoring host.

The Village also has a shared **workshop**, persistent project **noticeboard**,
**suggestion box**, and **practice cases**. Contributions retain evidence and
approval history. Read [how to use the Village infrastructure](docs/VILLAGE-INFRASTRUCTURE.md)
for ordinary Captain requests, exact owner approval commands and practice workflows.

On a supported 32GB Apple Silicon Mac, **Install Local AI.command now selects
the MiniCPM Captain profile automatically**. The older named Captain launcher is
a compatibility alias, not a second installation step. The installer builds the
pinned runtime and selects MiniCPM-V 4.7 35B-A3B as shared model, without
downloading the stock 9B analyst or 12B coder. The Captain and temporary workers
share model weights; native throughput remains unmeasured.

This release combines vision, Apple PDF/OCR, approved file workflows, background
startup and recurring text tasks with the scoped Mac controller and generic
external reasoning helper. It also contains the existing local text, Office,
image/video, speech, conversation, Discord and encrypted workspace tools.

Optional finite autonomous document jobs use the existing text gateway and a
checkpointed launchd worker. They read only a pre-authorised folder of small
UTF-8 files and create new Markdown outputs without model tool access. This is
not an unrestricted background OpenCode agent. See [autonomous jobs](docs/AUTONOMOUS-JOBS.md).

The installer now verifies a **fixed SHA-256** for the Apple Silicon `uv`
bootstrap, Docker Desktop 4.91.0 and the exact ComfyUI source archive.
It pins a mutually compatible Torch/TorchVision/TorchAudio set and freezes
remaining `uv` dependency resolution to the 16 October 2026 release window.
ComfyUI now has an 85-package transitive hash lock for macOS 15+ ARM64,
Python 3.12. Control, Open WebUI and shared speech/transcription environments
also use complete hashed package locks, including the speech build backend. See
[dependency lock scope](docs/DEPENDENCY-LOCKS.md).

Captain now selects **AtomicChat's abliterated MiniCPM-V 4.7** automatically:
the pinned standard Q3 weights and original vision projector plus its mandatory
106 MB LoRA adapter at scale 1.0. The installer downloads and verifies all
three artifacts, and every shared Captain/worker slot loads the adapter.
No separate activation step is required. Native Mac inference and vision
with this adapter remain unverified. See [model selection](docs/CAPTAIN-MODEL-SELECTION.md).

The actual remote Captain's web page and API share **one private
Tailscale HTTPS origin**, with no public LAN listener. Native CI exercises
the pinned OpenCode `web` command using a simulated tailnet hostname,
authenticated native agents and its server-sent event stream.
The Mac supervisor now holds a process-scoped idle-sleep assertion and
repairs only its missing private Tailscale routes after reconnects. It
will not enable public Funnel or bypass FileVault login.
Tailscale recovery and HTTPS checks run in one supervised background worker,
so slow repairs do not hold up health monitoring or the Captain watchdog.

See [headless and remote acceptance](docs/HEADLESS-AND-REMOTE-ACCEPTANCE.md)
for what still requires an iPad/Windows test and real reboot/sleep checks.

**Installation candidate only; owner-Mac end-to-end acceptance remains required.**
Local authoring tests do not establish GPU performance, microphone quality,
actual VPN tunnel-drop behavior, account approvals or memory pressure on your Mac.

## Deploy

1. Download the ZIP above using GitHub's download control and extract it.
2. Run **`Install Local AI.command` once** from the extracted `mac-local-ai-installer` folder.
3. Approve required Apple software/permissions during installation. When core
   acceptance passes, it starts the Captain, configures login startup and opens
   the Captain interface. Use `Local AI.app` or `Open Captain.command` later.

Requirements: native Apple Silicon, macOS 15+, 32 GB unified memory and at least
100 GB free space for the initial install. Existing installations upgrade in
place and retain local configuration and credentials. Stop Local AI before upgrading.

The Captain installer opens Cryptomator **during the initial installation** so
you can create/unlock the encrypted AI Workspace inside Cryptomator itself. It
then registers the confirmed mounted volume, prepares encrypted folders and
performs a write/read/cleanup check automatically. No separate workspace setup
script is required after installation. The encryption password and recovery
key stay with you, and future vault unlocks remain manual.

The Captain installer verifies real local inference and worker delegation before
registering a user-level login service, bringing up the managed Captain Work Agent,
and opening its authenticated local interface at http://127.0.0.1:4096.
Ordinary Open WebUI chat remains available at http://127.0.0.1:8081, but
**agent delegation happens in the Captain Work Agent, not ordinary chat**.
The installer prints the local Captain login details once; `Open Captain.command`
can display them again without reconfiguration.

**One Captain installer now provisions its intended network integrations during
installation**. It installs/validates Docker Desktop (owner accepts its licence in
the app), configures the signed Proton VPN-bound reader and Playwright browser
(owner enters a WireGuard key in Terminal), installs Tailscale (owner signs in and
approves macOS network permissions), and creates private HTTPS links to the
**actual Captain Work Agent** plus ordinary chat and media. It verifies the live
VPN, browser, Tailscale routes and authenticated Captain; incomplete mandatory
checks stop installation rather than claiming success.

The Captain is available on other devices at
`https://YOUR-MAC.YOUR-TAILNET.ts.net:10000`, on the personal Tailscale network
only, behind a separate local password. Open WebUI uses HTTPS 443 and media 8443.
Each other device needs Tailscale installed and signed into the same tailnet.
Neither the OpenCode backend nor model APIs are bound to the public internet.
See [remote access](docs/REMOTE-ACCESS.md).

| Capability | Status after the Captain installer |
| --- | --- |
| Vision and scanned PDFs | Installed and natively tested; chat uploads/agent PDF tools available |
| DOCX/XLSX/PPTX | Installed and Work Agent MCP-checked |
| Encrypted workspace | Guided Cryptomator creation/registration and file smoke test inside installation; owner unlock required after reboot |
| Login startup | Registered automatically |
| VPN search and browser | Local Docker, Proton Gluetun and VPN-only Playwright provisioned and checked during installation |
| Windows/iPad remote Captain | Private Tailscale Serve and OpenCode Basic Auth provisioned and checked from Mac; test from another device remains essential |
| GitHub connection | Secure fine-grained token requested during installation; only enabled if supplied, with chat selection/approval required |
| Recurring/autonomous tasks | Tools installed; individual scheduled jobs still require a user to specify and authorise their task |
| Scoped Mac control | Installed but deliberately isolated from regular Captain; separately approved control session required |
| Generic external reasoning | Installed, but never preauthorised against a third-party service without the owner's provider permission |

Desktop control and external-provider delegation use deliberately exclusive
safety profiles. They cannot safely run with normal effectful Captain tools.
Account/permission prompts occur **during** installation wherever possible,
not through separate setup scripts. An unprovided external account cannot be
honestly reported as tested. See [deployment](docs/DEPLOYMENT.md).

Scoped automation is a deliberately restricted profile. When enabled it disables
ordinary effectful tools and specialist delegation in the Work Agent, and disables
chat tool connections. Disable it to resume normal Office/file/browser workflows.
All capabilities are included in the same installation; their safety profiles
remain distinct. See [scope and privacy boundaries](docs/SCOPED-AUTOMATION.md).

## Known pre-installation gaps

See the [first-install failure audit](docs/PREINSTALL-FAILURE-AUDIT-2026-10-15.md)
for confirmed remaining blockers, the corrected interrupt/upgrade/slot issues,
and a first-Mac acceptance checklist. Green CI is not proof of a turnkey
installation on the owner's 32 GB Mac.

## Verify

The installer writes `~/LocalAI-Automated/captain-install-readiness.json` only
after the required native tests, encrypted workspace read/write test and live
Captain UI checks pass. The file lists
physical tests not yet observed and account-dependent services needing owner
authorisation. A valid receipt is not proof of reboot, sleep/wake, VPN-drop or
sustained 32GB-memory performance. The release ZIP is regenerated by CI from
the exact tested source on `main`; pull requests expose their own tested ZIP
as a workflow artifact instead of relying on the older checked-in archive.

[Release validation](docs/RELEASE-VALIDATION.md) separates completed authoring
checks from the native checks still required. Start with `Check Required
Capabilities.command`; use the dedicated browser, Office, conversation and
automation checks for capabilities you enable.

The installer ZIP is generated from the current source and guides. Its
`RELEASE.json` lists each packaged file's SHA-256 and the release identifier.
CI rejects stale package contents or missing executable permissions.

```bash
python3 scripts/build_installer.py --check
PYTHONPATH=installer:installer/payload python3 -m unittest discover -s installer/tests -v
PYTHONPATH=installer:installer/payload python3 -m unittest discover -s installer/payload/tests -v
node --test $(find installer/tests -name '*.mjs' ! -name 'test_conversation_browser.mjs')
```

The optional conversation browser UI test requires a separate Playwright Chromium
installation. Guides for individual features remain in [docs](docs/).
`manual-setup/` and its older ZIP are historical reference material and are not
the current deployment route. Model weights, generated outputs and credentials
do not belong in this repository.
