# Deploy LOCAL AI

Use `main` as the source of truth. The sole package path is
`downloads/Mac-Local-AI-Automated-Installer.zip`, but its checked-in contents are
an older snapshot and do not include all current source changes. Merging source
does not rebuild it. See [release validation](RELEASE-VALIDATION.md#current-source-and-package-status)
for the manual release gates and package/source verification.

## Installation or upgrade

1. Stop LOCAL AI and the Work Agent. Leave Docker open if you use VPN web access.
2. Obtain a validated installer matching the intended source revision and extract it.
   Do not assume the checked-in ZIP includes later source fixes.
3. Open `Install Local AI.command` inside `mac-local-ai-installer` to install
   **the MiniCPM Captain profile** automatically, or run:

   ```bash
   /bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI.command"
   ```

4. Keep Terminal open during installation. The installer downloads dependencies
   and models, resumes completed stages, preserves local configuration and runs
   its native acceptance steps. Review failures and any `not_run` results.
5. During installation Cryptomator opens for one-time secure vault creation or
   unlock in its own GUI. Confirm the decrypted mounted volume in Terminal.
   The installer registers and validates the encrypted workspace without
   a second post-install setup helper.
6. Still **inside this one installer**, Docker Desktop is installed/verified.
   Approve its administrator permissions and accept Docker's published licence
   within its app. Enter the Proton Free WireGuard private key through the
   hidden Terminal prompt. The installer provisions the VPN reader and
   VPN-only Playwright browser, starts them and performs live readiness checks.
7. Tailscale installs and opens. Approve its macOS network extension, sign into
   your personal tailnet and approve Tailscale HTTPS if prompted. The installer
   configures three private routes, including the **actual Captain**
   `https://MAC.TAILNET.ts.net:10000`. You may also provide a fine-grained
   GitHub token during installation. Missing account credentials do not
   silently turn into a configured connection.
8. Once native and network acceptance passes, the installer registers login startup,
   starts the managed Captain Work Agent at `http://127.0.0.1:4096`,
   checks the authenticated agent endpoint and opens Safari. Local login
   credentials are shown in Terminal; `Open Captain.command` displays them
   again if needed. Ordinary Open WebUI chat remains available at
   `http://127.0.0.1:8081`, but Captain worker delegation is in the Work Agent.
   Launch `Local AI.app` on future logins.

The installer uses a SHA-verified, versioned `uv` bootstrap, vendor-checked
Docker Desktop 4.91.0, an immutable ComfyUI commit/archive checksum, and
a pinned compatible PyTorch package trio. `UV_EXCLUDE_NEWER` prevents packages
published after the 2026-10-16 release cutoff from changing dependency
resolution. ComfyUI additionally uses an 85-package transitive hash lock for
macOS 15+ ARM64/Python 3.12. Control, WebUI and shared voice environments also
have artifact-hashed platform locks, with the documented immutable MLX source exception.
See [dependency lock scope](DEPENDENCY-LOCKS.md).

Remote OpenCode's UI and API share the exact same private Tailscale HTTPS
origin, with a native OpenCode `web` check of the authenticated API and event
stream. Cross-origin access is not needed for the standard remote UI.
During supervised sessions, `caffeinate -i -s` prevents idle sleep without
changing permanent macOS settings. The supervisor reopens Docker/Tailscale
and restores missing *owned* private routes on reconnect, refusing Funnel.
Real Windows/iPad browsing and reboot/sleep recovery remain pending.
See [headless/remote acceptance](HEADLESS-AND-REMOTE-ACCEPTANCE.md).

Apple Silicon, macOS 15+, 32 GB unified memory and at least 100 GB free space are
required. Installation needs Internet access for initial dependencies and models.
No model weights, personal files or account credentials are included in the ZIP.


## Optional Krea pixel-art model files

During Stage 4 the installer offers the Krea 2 Turbo base model and
`azyg0s/Krea-2-pixelart-lora` as an optional model component. Selecting it
downloads both gated Hugging Face repositories to
`models/pixelart/`; the large weights are not placed in the installer ZIP.
Before installing, review and accept each repository's current access terms on
Hugging Face. The installer then asks for a read token using a hidden prompt,
uses it only for those downloads, verifies each file against Hugging Face
metadata, and records the resolved repository revisions. It does not save the
token. The Krea 2 Community License and Acceptable Use Policy apply; review the
model card's revenue and deployment-filter requirements.

The model card's generation settings are 512×512, four steps and guidance 0,
followed by 32×32 sprite extraction. This installer stage prepares the model
files only. It does not yet add a studio workflow or claim native pixel-art
generation acceptance on the owner's Mac.

## Prepare personalised knowledge

After the installer completes, open `Village Commons.command` and use
**Prepare the Village from your conversation history**. Select the export once;
the system prepares Library content, memories and specialist residents for exact
owner approval. The raw corpus remains private. The same package includes
Commons, memory maps, encrypted Village recovery and managed-source forgetting.
[Founding and recovery](FOUNDING-AND-RECOVERY.md) explains the complete flow and scope.

## Account-bound and safety-separated capabilities

Core Captain installation no longer requires running extra model, login-startup
or encrypted-workspace registration launchers. The remaining items require
external accounts or deliberate changes to safety boundaries and therefore
cannot be enabled silently. Cryptomator owns the password/recovery key and
requires manual unlock after future logins. The installer must not describe these as verified.

| Use | Setup and checks |
| --- | --- |
| Ordinary images and PDFs | Upload in chat; inspect project images/PDFs in the Work Agent. Run `Check Required Capabilities.command`. |
| Office and file workflows | Installed with the Captain. Cryptomator registration and protected read/write testing occur during installation. Future unlocks and transfer approvals require owner interaction. |
| Start at login | Automatically registered by the Captain installer after native acceptance. A real logout/login check is still required. |
| Recurring text inference | Run `Schedule AI Task.command`; inspect `Scheduled Task Status.command`. Tool/command routes are blocked and cutoffs are reported as incomplete. |
| Finite autonomous document batch | Run `Create Autonomous Job.command` and explicitly approve the exact source folder, model and per-file instruction. Manage it through the dedicated Status/Stop/Resume commands. See `AUTONOMOUS-JOBS.md`. No unattended model tool calls. |
| VPN browser | Docker, Proton VPN and Playwright are installed, configured and checked **during** the Captain installer. A VPN-drop/leak stress test remains for the Mac. |
| Scoped desktop | The restricted code and policy are installed; activation must be separately approved in its isolated control session because it disables normal Captain effectful tools. |
| Generic external helper | VPN browser is provisioned, but third-party provider automation requires explicit permission, verified selectors and approval for every outgoing prompt. |

Scoped desktop/external automation disables other effectful model tools while
enabled. Run `Disable Scoped Automation.command` and restart to restore normal
Office, file and browser workflows. `Stop Automation.command` latches an emergency
stop; local rearm does not reactivate old sessions.

## Installation readiness receipt

The Captain installer writes `captain-install-readiness.json` in the
installation root only after encrypted workspace registration and live read/write
testing, required native text/media tests, the actual Captain worker delegation
test, the authenticated managed Work Agent/Chat UI startup checks, and
**live VPN, Playwright and private Tailscale Captain/Chat/media route verification** all pass. Failed checks abort installation and retain logs for repair.
The receipt identifies account-bound deferred services and unverified physical
journeys (especially off-device Captain, reboot, memory pressure and VPN-drop);
it does not claim the whole system has been proven.

The installed `Start Local AI.command` opens the already-running Captain when
the login supervisor is healthy rather than launching a duplicate backend.
`Open Captain.command` opens the managed agent and displays the local login
credentials. The ordinary Open WebUI window is a separate chat surface.

## Acceptance boundaries

Authoring suites test logic, local HTTP, MCP framing and synthetic responses.
The combined release has not been installed on the owner's Mac by this assistant.
Native GPU/memory, desktop approvals, actual provider/browser compatibility,
microphone, physical login/crash/sleep/wake and VPN-drop journeys still need
observed acceptance on that machine. Use the feature guides and record actual
outcomes. Do not equate an installer download or passing unit suite with those
results.
