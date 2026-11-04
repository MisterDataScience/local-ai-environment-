# Deploy LOCAL AI

Use source and an installer ZIP from the same revision. This branch rebuilds
`downloads/Mac-Local-AI-Automated-Installer.zip` for the modular implementation;
owner-Mac acceptance remains pending. See [release validation](RELEASE-VALIDATION.md)
and the [complete modular installer guide](MODULAR-INSTALLER.md).

## Installation or upgrade

1. Stop LOCAL AI and the Work Agent. Keep the existing installation and downloads.
2. Extract the matching source package and run `Install LOCAL AI Core.command`.
   The standard `Install Local AI.command` now has the same core-first default.
3. Complete Apple Command Line Tools if requested, then rerun. Core downloads its
   pinned model/runtime dependencies and verifies text, context protection, real
   delegation/retirement and the authenticated local Captain interface.
4. Core registers startup after macOS login and opens `http://127.0.0.1:4096`.
   `Open Captain.command` displays its local private credentials. Ordinary chat
   remains at `http://127.0.0.1:8081`. Both bind only to loopback.
5. Use `Check LOCAL AI Setup.command` for state, missing work and physical checks.
   Later, stop Local AI and run the named installer for the desired feature.
   No optional account, recording, vault or network input is needed for core.
6. `Install Everything.command` selects the same feature modules. Each incomplete
   feature is reported separately; unrelated installation work can continue.

Speech, Discord, media, Office, encrypted storage, VPN web/browser, Tailscale and
GitHub each have independent launchers. [The feature table](MODULAR-INSTALLER.md#independent-installers)
records dependencies and acceptance. Discord uses the live-conversation bridge
and needs a registered speech voice and STT/VAD. Its real call is tested separately.

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

Apple Silicon, macOS 15+, 32 GB unified memory and at least 35 GB free space for core are
required. Installation needs Internet access for initial dependencies and models.
No model weights, personal files or account credentials are included in the ZIP.

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
