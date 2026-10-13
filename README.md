# LOCAL AI

One source of truth: **`main`**. One deployment package:
[Mac-Local-AI-Automated-Installer.zip](downloads/Mac-Local-AI-Automated-Installer.zip).
Feature branches are development history, not installation choices.

The Work Agent now has a **captain and temporary workers**. One request can become
up to five independent workers with separate contexts, role-specific tools,
shared findings and peer messages. Compatible text requests can run concurrently
against one model; speech and media still use exclusive model handoffs.
Read [how the captain works](docs/CAPTAIN-AND-WORKERS.md).

For the planned 32GB Mac, **Install Local AI with MiniCPM Captain.command** in the
same ZIP builds the pinned native runtime and selects MiniCPM-V 4.7 35B-A3B as
the shared model. It omits the stock 9B analyst and 12B coder downloads. The regular
installer also provides the captain using the existing 4B model. Worker count
does not multiply model downloads. Native Mac throughput remains unmeasured.

This release combines vision, Apple PDF/OCR, approved file workflows, background
startup and recurring text tasks with the scoped Mac controller and generic
external reasoning helper. It also contains the existing local text, Office,
image/video, speech, conversation, Discord and encrypted workspace tools.

Optional finite autonomous document jobs use the existing text gateway and a
checkpointed launchd worker. They read only a pre-authorised folder of small
UTF-8 files and create new Markdown outputs without model tool access. This is
not an unrestricted background OpenCode agent. See [autonomous jobs](docs/AUTONOMOUS-JOBS.md).

**Ready for installation on Apple Silicon; owner-Mac acceptance remains required.**
Local authoring tests do not establish GPU performance, microphone quality,
actual VPN tunnel-drop behavior, account approvals or memory pressure on your Mac.

## Deploy

1. Download the ZIP above using GitHub's download control and extract it.
2. Run `Install Local AI.command` from the extracted `mac-local-ai-installer` folder.
3. Use the generated `Start Local AI.command` or `Local AI.app`.

Requirements: native Apple Silicon, macOS 15+, 32 GB unified memory and at least
100 GB free space for the initial install. Existing installations upgrade in
place and retain local configuration and credentials. Stop Local AI before upgrading.

The standard installer includes every capability's code. Optional services stay
disabled until their local setup is completed. There is no branch-specific second
installer. See [deployment and activation](docs/DEPLOYMENT.md).

| Capability | Activation after installation |
| --- | --- |
| Vision and scanned PDFs | Chat uploads or the Work Agent project tools; select a vision-capable model |
| DOCX/XLSX/PPTX | Work Agent and `Check Office.command` |
| Approved file handoffs | Work Agent transfer tools; vault must be manually unlocked |
| Background startup | `Enable Login Startup.command` |
| Recurring text tasks | `Schedule AI Task.command`; text-only route enforced by the gateway |
| Finite autonomous batches | `Create Autonomous Job.command`; separate explicit approval, read-only inputs, local new Markdown outputs, resumable job checkpoints |
| VPN search and browser | `Enable Web Access.command`, then `Enable Browser.command` |
| Scoped Mac control | `Enable Desktop Control.command`; Finder folders and Calculator only |
| Generic external reasoning | `Enable External Delegation.command`; provider permission, selectors and exact local approvals required |

Scoped automation is a deliberately restricted profile. When enabled it disables
ordinary effectful tools and specialist delegation in the Work Agent, and disables
chat tool connections. Disable it to resume normal Office/file/browser workflows.
All capabilities are included in the same installation; their safety profiles
remain distinct. See [scope and privacy boundaries](docs/SCOPED-AUTOMATION.md).

## Verify

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
