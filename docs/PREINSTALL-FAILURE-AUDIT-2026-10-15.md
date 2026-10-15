# LOCAL AI — first-install failure audit (15 October 2026)

**Scope:** repository `main` after the Captain/Cryptomator consolidation,
plus the corrections in this change set. Static inspection, existing CI, and
public upstream documentation only. **This is not an owner-Mac installation.**

## Verdict

**Not yet defensible as a zero-follow-up turnkey installation.**
The core Captain setup has tests and a managed local interface, but several
intended integrations remain disconnected or require post-install activation.
Actual Mac memory, camera/microphone and sleep/wake performance remain unknown.

## Confirmed issues

| Priority | Finding and evidence | Disposition |
| --- | --- | --- |
| P1 | The default Captain launcher starts `runtime.py`, which serves Captain through local-only OpenCode port **4096** (`installer/runtime.py`), while Tailscale setup explicitly exposes the Open WebUI/media proxy, **not the Captain's UI** (`installer/remote_access.py`). Other devices cannot use actual Captain orchestration through the existing remote chat URL. | **Open.** Requires a separately authenticated, tailnet-only Captain route and live off-device test. Do not directly expose port 4096 on the public network. |
| P1 | Default installer enables the MiniCPM Captain and sets up Cryptomator, but does **not** invoke remote-access, VPN/browser, desktop-control or GitHub credential setup without separate flags/commands (`installer/installer.py`, `installer/browser_setup.py`, `installer/automation_setup.py`). | **Open.** Fold safe provisioning into the single setup journey; obtain unavoidable consent/credentials inside installation. Some modes intentionally cannot be simultaneously active. |
| P1 | The GGUF server allocated KV cache capacity for the maximum five workers even in Normal mode, which permits only two (`installer/payload/shared_llama.py`, `model_engine.py`). | **Fixed in this branch.** Launch context/slots now follow active resource mode, preserve Max capability, and log native errors privately. |
| P1 | Hardware acceptance required the owner's current mode to already be Max; a normal-mode upgrade after code changes aborted and instructed manual mode switching (`installer/installer.py`). | **Fixed in this branch.** The stopped installer temporarily selects Max, tests and restores the chosen mode; fresh Captain installations launch in Normal to avoid allocating five slots during normal use. |
| P1 | On interruption after download completion but before renaming `.part` to the installed artifact, the universal installer downloader called `curl -C -` again, risking HTTP 416 and permanently blocking retries (`installer/installer.py`). | **Fixed in this branch.** Already-complete checksum-validated artifacts and complete ZIP files are promoted locally; reject symlinked partials. |
| P1 | The text-generation and Captain delegate acceptance is real only *inside the installer*; it does not prove every chat integration is selected, discoverable and usable in ordinary Open WebUI conversations (`installer/turnkey_install.py`, `installer/common.py`). | **Open.** Validate the two UIs independently and avoid labelling unselected integrations as operational. |
| P2 | No preinstalled reference speech voice is created. Speech is installed but `verify_generation` may emit `speech-generation: not_run` if `voice-engine/voices/default.json` is absent (`installer/voice_setup.py`, `installer/installer.py`). | **Open.** It needs a user-authorised reference recording or an appropriately licensed default voice. Never say voice generation passed when untested. |
| P2 | `torch`, `torchvision` and `torchaudio` are installed without locked versions, and ComfyUI is downloaded from a release tag without a pinned checksum (`installer/installer.py`). This reduces fresh-install reproducibility despite version pins elsewhere. | **Open.** Freeze tested ARM builds/hashes and validate dependency resolution on a clean runner. |

## Mac-only risks (not confirmed defects)

- The MiniCPM mixed-Q3 artifact + F16 projector + five 16K slots may exceed
  desirable unified-memory pressure at full concurrency on a 32 GB Mac. CI
  builds `llama-server` but **never loads the real GGUF weights**.
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
