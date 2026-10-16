# LOCAL AI — first-install failure audit (15 October 2026)

**Scope:** repository `main` after the Captain/Cryptomator consolidation,
plus the corrections in this change set. Static inspection, existing CI, and
public upstream documentation only. **This is not an owner-Mac installation.**

## Verdict

**Code-level integration implemented, owner-Mac acceptance still pending.**
Captain now has signed Docker installation, VPN-only browser setup, private
Tailscale Captain access and live integration gates inside its single entry point.
Scoped desktop mode and external provider access intentionally need separate
authorisation; ordinary WebUI per-chat tool selection remains distinct.
Actual Mac memory, camera/microphone and sleep/wake performance remain unknown.

## Confirmed issues

| Priority | Finding and evidence | Disposition |
| --- | --- | --- |
| P1 | Previously, Tailscale exposed Open WebUI/media but not the actual Captain at loopback port 4096. | **Fixed in the 16 October 2026 integration branch:** separately authenticated Tailscale Serve HTTPS 10000 routes to loopback OpenCode, with route conflict, 401/authenticated-agent and rollback checks. **Still unverified:** browser/WS behaviour from a second device on the physical Mac. |
| P1 | The Captain installer previously omitted Docker, VPN, browser and remote authentication setup, leaving separate activation scripts. | **Integrated in 16 October 2026 branch:** signed Docker installation, Proton VPN/Playwright and Tailscale/remote Captain setup run during the same installer, with private token consent and live checks. **Still unresolved:** scoped desktop mode is deliberately exclusive with normal agent tools; third-party external delegation requires provider authorisation; no full hardware run yet. |
| P1 | The GGUF server allocated KV cache capacity for the maximum five workers even in Normal mode, which permits only two (`installer/payload/shared_llama.py`, `model_engine.py`). | **Fixed in this branch.** Launch context/slots now follow active resource mode, preserve Max capability, and log native errors privately. |
| P1 | Hardware acceptance required the owner's current mode to already be Max; a normal-mode upgrade after code changes aborted and instructed manual mode switching (`installer/installer.py`). | **Fixed in this branch.** The stopped installer temporarily selects Max, tests and restores the chosen mode; fresh Captain installations launch in Normal to avoid allocating five slots during normal use. |
| P1 | On interruption after download completion but before renaming `.part` to the installed artifact, the universal installer downloader called `curl -C -` again, risking HTTP 416 and permanently blocking retries (`installer/installer.py`). | **Fixed in this branch.** Already-complete checksum-validated artifacts and complete ZIP files are promoted locally; reject symlinked partials. |
| P1 | The text-generation and Captain delegate acceptance is real only *inside the installer*; it does not prove every chat integration is selected, discoverable and usable in ordinary Open WebUI conversations (`installer/turnkey_install.py`, `installer/common.py`). | **Open.** Validate the two UIs independently and avoid labelling unselected integrations as operational. |
| P2 | No preinstalled reference speech voice is created. Speech is installed but `verify_generation` may emit `speech-generation: not_run` if `voice-engine/voices/default.json` is absent (`installer/voice_setup.py`, `installer/installer.py`). | **Open.** It needs a user-authorised reference recording or an appropriately licensed default voice. Never say voice generation passed when untested. |
| P2 | Previous ComfyUI/Torch installation used unversioned Torch packages and downloaded ComfyUI by a tag. | **Addressed in 16 October 2026 branch:** fixed Torch/TorchVision/TorchAudio versions, source commit and SHA-256, upgrade-marker validation, plus release-cutoff dependency resolution. Full transitive hash locking remains open. |
| P2 | The original bootstrap executed the latest upstream `uv/install.sh` and Docker Desktop used a floating download. | **Addressed in 16 October 2026 branch:** pinned SHA-verified ARM `uv` and signed Docker 4.91.0 DMG; native Mac CI validates the exact `uv` executable. |

Owner-Mac login, off-device browser approval, deliberate sleep/wake and
power-loss recovery remain unverified. The new LaunchAgent supervisor opens
Docker/Tailscale at login, keeps idle sleep away while running, restores missing
private Serve routes without stealing unrelated routes, and fails on public
Funnel. It **cannot unlock FileVault or start before the owner's macOS login**.
See [headless acceptance](HEADLESS-AND-REMOTE-ACCEPTANCE.md).

## Mac-only risks (not confirmed defects)

- The MiniCPM mixed-Q3 artifact + F16 projector + five 16K slots may exceed
  desirable unified-memory pressure at full concurrency on a 32 GB Mac.
  The GitHub `macos-15` standard runner is an Apple M1 with **7 GB RAM
  and 14 GB SSD** according to GitHub's runner reference, so the CI job
  builds `llama-server` but **cannot load the 14+ GiB Captain GGUF weights**
  on that runner. The real model/hardware compatibility is unmeasured.
  Source: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- macOS mounting, Cryptomator/iCloud synchronization, disk image signatures,
  LaunchAgent logout/login, sleep/wake, and microphone/permissions are not
  acceptance-tested on the owner's hardware.
- Large image/video and voice downloads, Mac Metal support and staged first-run
  generation may cause lengthy installation or failure. A successful ZIP
  package build cannot prove these services run simultaneously on target hardware.
- Browser via Proton requires Docker + account keys. Scoping desktop automation
  deliberately disables ordinary agent tools, so a naive 'enable everything'
  configuration would undermine the regular Captain experience.
- The first historical-conversations knowledge migration cannot happen without
  importing the user's exported files and is not yet proven as part of first run.

## Recommended release gate

1. **Single clean Mac installation**, capturing each stage, actual storage used
   and errors without credentials. Interrupt/resume once intentionally.
2. **Core native tests:** both GGUF Normal and Max inference, Captain-to-worker
   tool delegation, writing validated document outputs, media and encrypted
   workspace IO. Measure memory pressure and swapping.
3. **Interfaces:** Captain on the Mac, ordinary Open WebUI, and tailnet-only
   Captain and chat on an iPad/Windows device. Deny an agent edit and confirm
   no disk changes.
4. **Recovery:** reboot, log back in, unlock existing Cryptomator vault, verify
   files are only available while mounted, lock, attempt access and confirm
   refusal. Verify graceful shutdown and backup.
5. **Unattended path:** users should not need to run separate setup scripts
   after installation; owner identity/credential/approval prompts during the
   single install are allowed. Mark third-party integrations unverified until
   their own authenticated smoke tests pass.

Do not close issue #7 based on CI alone. Keep the remaining findings tracked.
