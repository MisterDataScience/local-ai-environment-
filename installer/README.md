# Reverse essay scaffolding

Use Scaffold Essay.command to turn a supplied assignment brief into a staged,
question-led plan. Each stage requires author review and exact-version approval.
It does not write answers or activate editing. See REVERSE-ESSAY-SCAFFOLDING.md.

# Optional essay editing

After updating, use Edit Essay.command with a UTF-8 .md or .txt draft. It reuses
the document model, preserves the original and saves separate editing notes.
See ESSAY-EDITING.md in the bundle for usage, limits and required author review.

# Update: Cryptomator workspace and GitHub

Discord integration is included in the main installer. One-time setup connects
an owner-only private voice channel and your saved voice. The bot starts with
Local AI, routes speech through the existing coordinator, and presents tool
approvals in Discord. See [Discord setup and live-call checks](../docs/DISCORD.md).
Live calls on the target Mac remain unverified.

Qwen3-TTS 1.7B Base is included as a locally downloaded MLX speech model.
Discord setup registers your default voice from a WAV reference and transcript
if you have not already saved one. Configure Voice.command adds other voices. See VOICE-GENERATION.md in the ZIP for `/speak` and coordinator usage.

Coordinator image/video tools now use the existing serial rendering backend,
with native approval prompts, saved job records and resource-mode checks.
See COORDINATOR-MEDIA.md in the ZIP for usage and the abliterated model review.

Team handoffs now use acceptance contracts and recoverable full reports, with
deterministic checks against native test/inspection records and no extra model
judge. See WORK-AGENT.md in the ZIP for the schema and plaintext storage caveats.

The installer now includes Cryptomator. After installation, stop Local AI and run
`~/LocalAI-Automated/Configure AI Workspace.command`, then optionally
`~/LocalAI-Automated/Connect GitHub.command`. See ENCRYPTED-WORKSPACE.md in the ZIP
or [the current guide](../docs/ENCRYPTED-WORKSPACE.md).

No vault password is saved or sent to the AI. You create and unlock the vault in
Cryptomator, then select the unlocked volume in the helper. GitHub credentials
are handled separately with hidden input and local private file storage.
Vault mode saves image/video output directly into the unlocked vault.
Chat history/uploads stay local, with offline vault backups and restore helpers.
Archive Existing AI Files preserves old generated media URLs and local originals. Account connections
must be enabled in chat Integrations and live-tested; approval is experimental.

# Automated Local AI Installer for Your Mac

This replaces the manual installation sequence with one installer for an **Apple Silicon Mac, 32GB or more unified memory, macOS 15 or newer**. Have **100GB free SSD space**, a working internet connection and mains power before starting.

## Run it

Optional web search/page reading is included. Read [WEB-ACCESS.md](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/WEB-ACCESS.md), also included beside this README in the ZIP, for Docker/Proton prerequisites and `Install Local AI with Web Access.command`. Add `--remote-access` for both retrieval and private other-device access in one run. VPN/DNS leak validation remains pending.

1. Download **Mac-Local-AI-Automated-Installer.zip**.
2. Extract it in Downloads. The resulting folder should be `mac-local-ai-installer`.
3. Open Terminal using Command + Space, type Terminal, then press Return.
4. Paste this exact command and press Return:

```bash
/bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI.command"
```

5. Leave Terminal open while it works. Model downloads are large, and the video acceptance test may take a long time. The installer prints its current stage. macOS may request approval to run downloaded software.
6. When installation and acceptance tests succeed, it starts the system and opens Safari at **http://127.0.0.1:8081**. Choose Everyday (`local-ai`), Small (`local-ai-small`) or Large (`local-ai-large`) in the model selector. Everyday remains the default.

No Homebrew commands, manual model placement, environment activation, API-key copying, WebUI provider setup or account creation are required. The installer uses a local single-user WebUI with login disabled, bound exclusively to loopback. Keep the native listeners on loopback. For access from your other devices, use the optional private Tailscale stage described below.

## What it installs

The gateway keeps model loading/unloading and serial media handoffs. Open WebUI owns tools and approvals; the gateway passes function definitions, calls and results between it and Ollama. The former private tool loop, calculator/time workers and disabled GitHub adapter are removed. See [native tools](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/NATIVE-TOOLS.md), also included in the ZIP. VPN setup registers a server-side OpenAPI connection named Local AI VPN retrieval; enable it in the chat's Integrations menu or attach it to a model. The same connection can expose opt-in Yandex reverse image search after `Configure Reverse Image Search.command` is run. GitHub can be configured with the new helper; no account credential is included.

| Component | Choice |
| --- | --- |
| Text backend/model | Native Ollama 0.40+ with Huihui Qwen3.5 4B/9B and Gemma4 12B Coder (Q4_K_M) |
| Image backend/model | Native ComfyUI MPS with SDXL Base 1.0 |
| Video model | LTX-Video 2B v0.9.5 and FP16 T5 encoder |
| Chat UI | Open WebUI 0.11.1, configured automatically |
| Gateway | Included Python gateway, serial model handoffs |
| Python installation | Private uv-managed environments |
| Video encoder | Included FFmpeg through imageio-ffmpeg's macOS ARM64 wheel |

ComfyUI is pinned to release v0.38.0. PyTorch and its dependencies are resolved when you install, then their installed versions are recorded. Ollama 0.40.0 is the pinned minimum for native context protection. A compatible private copy is reused; otherwise the official 0.40.0 macOS archive is downloaded with SHA-256 and code-signature verification. The previous private app is retained during upgrade, and its CLI is used without launching the desktop interface. Nothing signs into a cloud-model account.

All installation files are under **`~/LocalAI-Automated`**. The launcher is created at **`~/Applications/Local AI.app`**, with a Terminal fallback at **`~/LocalAI-Automated/Start Local AI.command`**. The previous manual guide's `~/LocalAI` directory is separate. This installer also uses separate ports so it does not need to stop an existing setup.

The official application archive and software dependencies can change independently of this bundle. If a download, dependency resolution or native compatibility check fails, the installer stops with a recorded error instead of claiming success.

## What is automated

The eight stages are:

1. Check architecture, macOS, memory, free disk space and port availability.
2. Download and verify the official Ollama app, placing a private copy in the installation directory.
3. Install ComfyUI, its separate Python environment and Apple GPU dependencies; check MPS availability.
4. Download all three image/video model files, resuming partial downloads and verifying publisher SHA-256 checksums.
5. Install the gateway and Open WebUI, generate local secrets and configure the provider/default model/background-task settings.
6. Start the services, prepare and verify all configured text models, check workflow schemas, test each text model and run **text, image, text, video, text** generation tests with WebUI running.
7. Create the daily launcher and save installed-version records.
8. Start Local AI and open Safari.

Tests run through the gateway; WebUI startup and provider configuration are checked separately. These are not browser-automation tests of every WebUI interaction. Visual quality is not automatically judged. The default video acceptance test uses **512 x 320, 17 frames, 12fps**, about 1.4 seconds, with no audio.

Successful acceptance runs save **`~/LocalAI-Automated/acceptance-report.json`**, including timings and output links. A passing check confirms execution and model handoff for that tested configuration. It does not promise long or high-resolution video will fit.

## Use it after installation

Open **Local AI.app** from your home folder's Applications directory. It opens the service supervisor in Terminal and then opens Safari once the services are ready. Leave that Terminal window open during use.

If Finder refuses the unsigned personal launcher, use the normal macOS Open action or this Terminal fallback:

```bash
/bin/bash "$HOME/LocalAI-Automated/Start Local AI.command"
```

You interact with the chat UI:

```text
Explain this Python function.        -> text
/image A red car beside a loch.      -> image
/video A red car slowly driving.     -> video
/search Python official tutorial    -> VPN search, if configured
/read https://www.python.org/        -> VPN page summary, if configured
/reverse Inbox/photo.jpg              -> VPN-only Yandex reverse image search, if configured
```

Team profiles use the 4B coordinator (8K), 4B document reader (32K), 9B analyst (32K) and 12B coder (16K). One model runs at a time. A model or context-profile change unloads the previous runner first. New idle timeouts are 120 seconds; upgrades preserve existing timeouts. Gaming allows coordinator/legacy-small text only, with 4K context and 1K output. Normal allows the team and images; Max also permits video and other configured models. Wait for Ready after switching. See RESOURCE-MODES.md and WORK-AGENT.md in the ZIP.

The gateway unloads Ollama and confirms an empty loaded-model list before starting ComfyUI. After each image or video job, it stops ComfyUI's process group and waits for exit before allowing text to reload. Multiple gateway requests are serialised. Do not connect another client directly to this private Ollama server or manually start ComfyUI on its private port during use.

Each inference response is buffered until complete; structured tool calls are preserved in both normal and SSE responses. Open WebUI handles execution and continuation. Images appear in chat and video returns an MP4 link. Optional web commands still supply bounded evidence and sources. Reverse image search, when separately configured, accepts only an encrypted-workspace image path, strips metadata into a local derivative and sends it to Yandex through the loopback-only Gluetun HTTP proxy with no direct fallback. Native document/memory/notes/code tools belong to Open WebUI and need their own configuration and validation. Image understanding, image-conditioned video, voice and automatic media routing are not implemented by the gateway.

## Optional reverse image search

This feature requires the encrypted AI Workspace and VPN web access first. While Local AI is stopped, run:

```bash
/bin/bash "$HOME/LocalAI-Automated/Configure Reverse Image Search.command"
```

Enter the Yandex Cloud folder ID and Search API key locally. The key is hidden during entry and stored in the owner-only local configuration. Restart Local AI afterward. The tool is never invoked automatically. It reads only a path explicitly selected inside the encrypted workspace, creates a metadata-free bounded JPEG derivative and sends that derivative through `http://127.0.0.1:8888`, Gluetun's HTTP proxy. If VPN health or the proxy fails, the search fails rather than trying the ordinary connection. Yandex still receives the derivative image itself.

See `docs/WEB-ACCESS.md` for Yandex role/scope setup, privacy boundaries and native validation requirements.

## Shutdown

Press **Control + C** in the Local AI Terminal. The supervisor stops WebUI, waits for the gateway to finish or time out and release its renderer, then stops Ollama. An active video can delay shutdown. Leave the window open until shutdown finishes; closing Safari alone does not stop the services.

## Resume a failed or interrupted install

Run the same installation command again. It reuses installed tools, preserves your WebUI data and edited workflows, resumes partial downloads and checks completed model files against the publisher hashes. Completed generation tests are reused only while the gateway/workflow/configuration fingerprint matches.

Do not run two installers simultaneously. If Local AI is already running, stop it before rerunning installation. The installer refuses occupied ports instead of killing unrelated applications.

Logs are under **`~/LocalAI-Automated/logs`**:

- `install.log`: stage progress and installation failures.
- `ollama.log`: text-server startup.
- `gateway.log`: request handling and orchestration.
- `webui.log`: chat-interface startup.
- ComfyUI rendering details: `~/LocalAI-Automated/control/logs/comfy.log`.

If a Mac GPU operation or memory allocation fails, installation stops and preserves the files/report produced so far. It does not disable Apple's or PyTorch's memory safeguards. A video timeout is one hour. A failed minimal video test needs diagnosis, rather than a claim that the complete system works.

## Files, backups and removal

Chats live in **`~/LocalAI-Automated/webui/data`**. Generated files live in **`~/LocalAI-Automated/control/media`** and ComfyUI's output folder. Secrets are stored in `control/config.json` with owner-only permissions. Back up chat data, generated files, configuration and workflows with Time Machine. Stop services before copying a live database manually.

To remove the installation, stop Local AI, then use Finder to move `~/LocalAI-Automated` and its `~/Applications/Local AI.app` launcher to the Bin. That removes this installation's models, chats and generated outputs, so retain any files you want first. No system Python, shell profile, Homebrew installation or unrelated Ollama installation is changed.

## Validation provided with this bundle

The bundle includes unit/integration tests for verified downloads, interrupted downloads, bad hashes, archive traversal, checkpoints, local-only provider configuration, process shutdown, application-overwrite protection, gateway routing, serialisation, unload confirmation and renderer cleanup. The authoring environment has no Apple GPU and no model weights. The installer performs the actual native dependency and generation checks on your Mac.

Primary references:

- https://docs.astral.sh/uv/getting-started/installation/
- https://docs.ollama.com/macos
- https://ollama.com/download/mac
- https://docs.ollama.com/api/ps
- https://docs.ollama.com/api/generate
- https://docs.comfy.org/installation/manual_install
- https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.38.0
- https://docs.openwebui.com/getting-started/quick-start/
- https://docs.openwebui.com/reference/env-configuration/
- https://comfyanonymous.github.io/ComfyUI_examples/ltxv/
- https://pypi.org/project/imageio-ffmpeg/

Initial installation needs internet. Inference is configured to use local services. This is not a notarised commercial Mac application or an air-gapped package; macOS and third-party software may still present first-run approvals or perform their own update checks.

## Text presets and timeout configuration

Edit `~/LocalAI-Automated/control/config.json` while services are stopped. Profiles define `model`, `role`, `name`, `keep_alive_seconds`, `num_ctx` and `thinking`. Role-specific maximum contexts are 8K coordinator, 32K analyst/document and 16K coder. Legacy/custom presets remain capped at 16K. Contexts can be reduced to 512. Output ceilings remain 1K/4K/8K for Gaming/Normal/Max and at most half the profile context. Timeouts are 0–3600 seconds. Restart to apply changes.

The installer migrates recognized stock entries once and saves `config.before-model-team-v1.json` privately. Custom entries and credentials survive; team roles receive separate IDs where needed. Team artifact files total roughly 17.3 GB; runtime memory also includes context/buffers, and retained legacy downloads still occupy disk. Native memory and accuracy validation remain required. Set `model_team.enabled` to false to disable OpenCode delegation.

To upgrade an earlier installation, stop Local AI, extract this updated bundle and rerun the same installation command. The installer removes only the named retired project modules and their tests from control; chats, models, workflows and credentials are preserved. The obsolete tool_loop_enabled config flag is ignored. Changed code/configuration invalidates the previous acceptance fingerprint. The installer runs generation checks again and stops if any configured model fails.

## Optional private remote access

To include Tailscale in the installation, run this wrapper instead of the ordinary command:

```bash
/bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI with Remote Access.command"
```

After local model checks pass, the installer downloads/verifies the official Tailscale standalone package if needed, asks macOS to install it, opens Tailscale for your sign-in/extension approval and configures private HTTPS for chat and generated media. Approve Tailscale HTTPS if prompted. An existing Tailscale app is reused without replacement. No password/auth key is stored by Local AI.

Install Tailscale on your other devices and sign in to the same personal account. Bookmark the Chat address in `~/LocalAI-Automated/Remote AI Address.txt`. The Mac must stay awake and Local AI must be running. The two private HTTPS ports are 443 for chat and 8443 for media. The additional media-only listener is loopback port 8002; it does not expose the gateway API.

Access uses Tailscale's permissions and the existing single-user WebUI database, without a separate WebUI password. Permitted tailnet devices/users see the same chats and media. Keep this on your personal tailnet. The helper does not enable Funnel, exit-node routing, public port forwarding or Proton search.

The updated installer also creates Enable Remote Access.command and Disable Remote Access.command under `~/LocalAI-Automated`. Stop Local AI before running either and restart afterward. Enabling later does not redownload models. Disabling removes only the matching Local AI routes, leaving Tailscale and other services in place.

Runtime checks HTTPS chat health and a temporary media file, recording `remote-acceptance-report.json`. A failure is reported while local chat continues. A real iPad/phone/Windows browser check is still required. Existing localhost links in old chats are not migrated. New media links use the private address.

This remains a Terminal-supervised application; remote access does not add automatic background startup or wake-on-demand. The installer may require a restart if macOS/Tailscale requests one. Resume setup after that restart.

## OpenCode work harness

`Start Work Agent.command` launches the installed upstream OpenCode in a copied
project, using the local gateway and its own web UI. Normal/Max only. Read
WORK-AGENT.md in this ZIP before approving shell commands. Work-agent files are
local, not automatically in the vault or its WebUI backups.

### Context management

The installer enables Open WebUI's existing conversation compaction at a conservative
1,536-token threshold suitable for the smallest presets. OpenCode retains its native
compaction and pruning. Gateway reply limits and structured failures support these
clients; no duplicate summariser is installed. Large individual inputs still need
care: see [context management and Mac acceptance](../docs/CONTEXT-MANAGEMENT.md).


### Longer output on the 32 GB M6 Mac mini

Team contexts are 8K coordinator, 32K analyst/document and 16K coder, with up to 4K output in Normal and 8K in Max, further bounded to half context. Gaming remains 4K context/1K output. The installer migrates recognised stock contexts once and preserves custom values. Ollama length cutoffs are reported accurately in JSON and SSE; each preset receives a native eight-token cutoff acceptance check. Existing one-model concurrency, unloading and GPU memory safeguards remain in place.

These profile sizes must be validated on the actual 32 GB Mac with normal background applications and the optional Docker stack. A short acceptance response does not establish maximum-length performance or memory pressure. Read CONTEXT-MANAGEMENT.md for long-response testing and smaller-context fallback settings. Reinstall the full updated bundle with services stopped; do not copy only gateway.py.

Context protection now rejects oversized requests instead of silently discarding input. WebUI compaction follows the active mode (1,536/8,192/6,144 token triggers for Gaming/Normal/Max with stock contexts); smaller custom contexts lower the budgets. OpenCode reserves room for output and tool work. Native acceptance checks oversized first messages, history, tool results and tool definitions on every preset. Summaries remain lossy, and large documents still need splitting or retrieval. See [context management](../docs/CONTEXT-MANAGEMENT.md).


## OpenCode team update

`Start Work Agent.command` starts Plan/Build with the 4B coordinator. Native
foreground tasks can use analyst/coder, at most two attempts per explicit user
turn including one concrete-failure retry. The coder can inspect files, edit and
run tests with native approval in Build or direct `/code`; Plan delegation is
read-only. It is limited to 12 model steps and 24 tool attempts. Analyst/document
agents have no tools and no specialist can delegate.
Direct `/code`, `/analyse` and `/document` commands avoid the coordinator pass.
Startup verifies the policy loaded. Mode changes or gateway restarts stop the
work agent. The installer also requires actual native handoff acceptance before
recording installation success. WebUI delegation and image input remain deferred.
Read WORK-AGENT.md for details, local storage, limits and native validation.
