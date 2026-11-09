# Core first, features when needed

Start with `Install LOCAL AI Core.command`. The existing `Install Local AI.command`
and named MiniCPM launcher are aliases for this default. Core installs the pinned
MiniCPM Captain, its real OpenCode workers, one small Qwen3.5 fallback, gateway,
local chat and login startup. It requires native Apple Silicon, macOS 15+, 32 GB
memory, Apple Command Line Tools and 35 GB free space. Missing downloads still
need internet access. Existing presets and downloaded models are preserved.

Core never requests a Discord token, reference recording, vault, Docker licence,
Proton key, Tailscale login or GitHub credential. Its native text, context/output
limits, real worker dispatch and retirement, authenticated Captain UI and MCP
policy checks must pass. Unit tests cannot satisfy those gates.

Captain: `http://127.0.0.1:4096`. Ordinary chat: `http://127.0.0.1:8081`.
Both bind to loopback. Existing Screen Sharing can display them on the Mac.
A remote web address is available only after Remote Access passes its checks.

## macOS blocks a downloaded launcher

The `.command` launchers are unsigned. For an unidentified-developer or
cannot-verify warning, try opening only `Install LOCAL AI Core.command`, dismiss
the warning, then open **System Settings > Privacy & Security**. In Security,
use **Open Anyway** for that exact launcher and confirm **Open**. This is Apple's
[per-item approval procedure](https://support.apple.com/en-gb/102445).

Core, Everything and the older MiniCPM alias now hand the shared launcher to
`/bin/bash`, matching the existing Web/Remote aliases. They no longer directly
execute a second downloaded `.command` file. The initial Finder approval may
still be required. Do not open all the optional installers to reach core chat.

If the alert says software contains malware or will damage the Mac, leave it
blocked. That is a different warning from an unidentified developer. A Terminal
**Paste blocked** alert is also separate; see Apple's
[Terminal alert guidance](https://support.apple.com/en-gb/127377).

## Independent installers

Stop Local AI and its Work Agent before changing an installation. Each launcher
works from Finder or Terminal, uses `~/LocalAI-Automated`, preserves downloaded
files and updates only its own configuration section. Afterward, run
`Start Local AI.command`. No core reinstall is needed between optional installs.

| Launcher | Prerequisite | Inputs and native acceptance |
| --- | --- | --- |
| Install Encrypted Workspace.command | Core | Signed Cryptomator, owner-confirmed mounted vault, real protected write/read/cleanup. Existing vault identity is retained. |
| Install Local Speech.command | Core | Shared voice environment and pinned TTS weights; default 3 to 30 second 16-bit PCM WAV with exact transcript; offline synthesis and WAV validation. Blank input defers enrolment. |
| Install Live Conversation.command | Local Speech | Pinned STT/VAD in the same environment; generated speech to STT/VAD round trip. Microphone, echo cancellation and barge-in remain physical follow-ups. |
| Install Discord Voice.command | Live Conversation | Pinned transport, Keychain bot credential and private owner-controlled channel. Setup and codec checks leave it configured until a real call passes. |
| Test Discord Voice.command | Configured Discord Voice | Ten-minute supervised call: private connection, owner speech, response playback and interruption must all be observed before ready. Reuses the authenticated managed Captain. |
| Install Image and Video.command | Core | Verified ComfyUI/Metal and pinned weights; real image and video generation, model release and return to text. Existing vault policy applies. |
| Install Office Tools.command | Core | Hash-verified AIOffice; macOS network sandbox and actual Office MCP document checks. |
| Install Encrypted Web Access.command | Core | Signed Docker, owner licence/permissions and Proton WireGuard key; VPN search/page, tunnel-outage rejection and external traffic checks. |
| Install Browser Automation.command | Encrypted Web Access | Pinned Playwright container in the VPN namespace and MCP acceptance. No host-browser fallback. |
| Install Remote Access.command | Core | Signed Tailscale and owner authorisation; private HTTPS and Captain authentication tests. Another-device acceptance remains separate. |
| Connect GitHub.command | Core | Explicit scoped token; official MCP identity check. Write approval checks remain separate; no test write is performed automatically. |

`Install Everything.command` selects these same feature modules after core. A
missing input or failed optional module is recorded and unrelated modules can
continue. Dependent modules wait for their prerequisites. It never claims that
an incomplete full installation is ready. Discord live-call acceptance is a
separate supervised command.

## State, recovery and capabilities

`Check LOCAL AI Setup.command` prints core and feature status, missing work, exact
installer names and tests not run. The gateway health probe is read-only.
`captain-install-readiness.json` records core acceptance separately from optional
receipts in `state/features/*.json`.

States are `not_installed`, `installed`, `awaiting_user`, `configured`, `testing`,
`ready`, `failed` and `disabled`. Receipts record versions, verified hashes,
dependencies, check time, failure class and the next action. They contain no
credentials. Private atomic writes and a shared installation lock prevent
concurrent installer/runtime mutation. Re-running repairs or reuses the same
private environments and verified downloads.

Saved owner settings remain intact. An in-memory runtime view withholds optional
features until their own receipt and prerequisites are ready. Changed deployed
installer/check source invalidates earlier feature readiness until rechecked.
Malformed optional receipts fail closed without stopping text chat. Unavailable
optional browser/Office connections are withheld from Captain startup.

The Captain, gateway discovery and studios use the declared state. Unavailable
commands identify their installer before loading a model. Studio/Synod and
institutional tools are withheld until encrypted workspace acceptance passes;
FileVault, Village path checks and institutional grants still apply afterward.
An existing vault's storage policy is always retained, even if locked or awaiting
acceptance. Sensitive writes never fall back to local plaintext media storage.

For an interrupted full installation, stop the existing services and run Core
from this source package. Keep `~/LocalAI-Automated`, `~/local-ai-source`, cached
archives and model directories. Existing optional settings enter configured
state and require their independent checks. A previous PR #40 trial's private
`control/trial-deferred-settings.json` is restored once and retained for recovery.
Missing or invalid recovery data stops migration without deleting it.

HTTP 401 from Discord means the bot credential was rejected. It does not diagnose
invite permissions. The failure is confined to Discord. To replace a saved token
explicitly, use `Connect Discord.command`, then rerun its feature installer.
Tokens remain in Keychain. Speech registration and Discord enrolment are separate.

## Native acceptance still required

The modular installer is an implementation candidate. This authoring environment
cannot execute Apple GPU inference, Finder launch, the owner's interrupted Mac
installation, real Discord audio or macOS permission grants. No owner-Mac pass is
implied by source tests or a freshly rebuilt ZIP.

On the Mac, record a fresh core run and a resume of the existing interrupted
installation. Verify a Captain answer and actual worker reports/retirement, then
start, stop and restart. Install two independent optional features in separate
sessions. Defer a missing WAV, reject an invalid Discord token and interrupt a
model download, confirming core remains usable and reruns preserve progress.
Unlock the same existing vault and confirm its identity and data survive.

Login startup is a user LaunchAgent after macOS login. FileVault pre-login unlock
is still manual. Vault unlock after login, physical sleep/wake, microphone and
off-device checks are recorded separately. VPN acceptance never substitutes for
the documented packet-capture/DNS and sustained failure journeys.
