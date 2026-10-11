# Deploy LOCAL AI

Use `main` and `downloads/Mac-Local-AI-Automated-Installer.zip`. This is the only
current installer package. It includes both formerly separate capability updates
and the audit corrections.

## Installation or upgrade

1. Stop LOCAL AI and the Work Agent. Leave Docker open if you use VPN web access.
2. Download the current installer ZIP from the repository and extract it.
3. Open `Install Local AI.command` inside `mac-local-ai-installer`, or run:

   ```bash
   /bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI.command"
   ```

4. Keep Terminal open during installation. The installer downloads dependencies
   and models, resumes completed stages, preserves local configuration and runs
   its native acceptance steps. Review failures and any `not_run` results.
5. Launch `~/LocalAI-Automated/Start Local AI.command` or `Local AI.app`.

Apple Silicon, macOS 15+, 32 GB unified memory and at least 100 GB free space are
required. Installation needs Internet access for initial dependencies and models.
No model weights, personal files or account credentials are included in the ZIP.

## Activate the capabilities you use

The same installer provides all helpers. Optional activation is local setup,
not another code branch or a second deployment.

| Use | Setup and checks |
| --- | --- |
| Ordinary images and PDFs | Upload in chat; inspect project images/PDFs in the Work Agent. Run `Check Required Capabilities.command`. |
| Office and file workflows | Run `Check Office.command`; use native transfer approvals. Configure and manually unlock Cryptomator for vault operations. |
| Start at login | Run `Enable Login Startup.command`; verify the next login and use `Stop Local AI.command` for graceful shutdown. |
| Recurring text inference | Run `Schedule AI Task.command`; inspect `Scheduled Task Status.command`. Tool/command routes are blocked and cutoffs are reported as incomplete. |
| Finite autonomous document batch | Run `Create Autonomous Job.command` and explicitly approve the exact source folder, model and per-file instruction. Manage it through the dedicated Status/Stop/Resume commands. See `AUTONOMOUS-JOBS.md`. No unattended model tool calls. |
| VPN browser | Set up Docker/Proton through `Enable Web Access.command`, then `Enable Browser.command`. Run `Check Browser.command` and verify tunnel failure stops browsing. |
| Scoped desktop | Run `Enable Desktop Control.command`, then `Check Desktop Control.command`. Open the Work Agent to use locally approved Finder/Calculator sessions. |
| Generic external helper | Enable and verify VPN browser first, then run `Enable External Delegation.command`. Provider permission and verified selectors are required. Every exact outgoing prompt needs local approval. |

Scoped desktop/external automation disables other effectful model tools while
enabled. Run `Disable Scoped Automation.command` and restart to restore normal
Office, file and browser workflows. `Stop Automation.command` latches an emergency
stop; local rearm does not reactivate old sessions.

## Acceptance boundaries

Authoring suites test logic, local HTTP, MCP framing and synthetic responses.
The combined release has not been installed on the owner's Mac by this assistant.
Native GPU/memory, desktop approvals, actual provider/browser compatibility,
microphone, physical login/crash/sleep/wake and VPN-drop journeys still need
observed acceptance on that machine. Use the feature guides and record actual
outcomes. Do not equate an installer download or passing unit suite with those
results.
