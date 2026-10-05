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

The gateway has separate HTTP, model, routing, workflow and tool modules. Installation copies them together. A bounded internal loop supplies calculator/current-time tools for ordinary chat. See [tool loop](https://github.com/MisterDataScience/local-ai-environment-/blob/main/docs/TOOL-LOOP.md). Search/media remain explicit commands; account connectors are not included.

| Component | Choice |
| --- | --- |
| Text backend/model | Native Ollama with Qwen3 4B, 14B and 30B-A3B (Q4_K_M) |
| Image backend/model | Native ComfyUI MPS with SDXL Base 1.0 |
| Video model | LTX-Video 2B v0.9.5 and FP16 T5 encoder |
| Chat UI | Open WebUI 0.11.1, configured automatically |
| Gateway | Included Python gateway, serial model handoffs |
| Python installation | Private uv-managed environments |
| Video encoder | Included FFmpeg through imageio-ffmpeg's macOS ARM64 wheel |

ComfyUI is pinned to release v0.38.0. PyTorch and its dependencies are resolved when you install, then their installed versions are recorded. The official Ollama application archive is downloaded at installation time, code-signing is checked and its native CLI is used without launching the Ollama desktop interface. Nothing signs into a cloud-model account.

All installation files are under **`~/LocalAI-Automated`**. The launcher is created at **`~/Applications/Local AI.app`**, with a Terminal fallback at **`~/LocalAI-Automated/Start Local AI.command`**. The previous manual guide's `~/LocalAI` directory is separate. This installer also uses separate ports so it does not need to stop an existing setup.

The official application archive and software dependencies can change independently of this bundle. If a download, dependency resolution or native compatibility check fails, the installer stops with a recorded error instead of claiming success.

## What is automated

The eight stages are:

1. Check architecture, macOS, memory, free disk space and port availability.
2. Download and verify the official Ollama app, placing a private copy in the installation directory.
3. Install ComfyUI, its separate Python environment and Apple GPU dependencies; check MPS availability.
4. Download all three image/video model files, resuming partial downloads and verifying publisher SHA-256 checksums.
5. Install the gateway and Open WebUI, generate local secrets and configure the provider/default model/background-task settings.
6. Start the services, download all configured Qwen3 models, check workflow schemas, test each text model and run **text, image, text, video, text** generation tests with WebUI running.
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
```

Text presets default to Small: 120 seconds idle, Everyday: 300 seconds and Large: 60 seconds. No model loads merely from selecting it. A text request for a different model explicitly unloads the old model first. These choices do not enforce Gaming Mode; image/video commands remain available from every preset.

The gateway unloads Ollama and confirms an empty loaded-model list before starting ComfyUI. After each image or video job, it stops ComfyUI's process group and waits for exit before allowing text to reload. Multiple gateway requests are serialised. Do not connect another client directly to this private Ollama server or manually start ComfyUI on its private port during use.

Text responses are buffered until complete. Images appear in chat. Video returns an MP4 link. Optional web commands supply bounded evidence and clickable sources to the local model. Image understanding, image-conditioned video, document RAG, voice, arbitrary tool execution and automatic natural-language media/web routing remain unsupported.

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

Edit `~/LocalAI-Automated/control/config.json` while services are stopped. The `text_models` entries set `model`, `name`, `keep_alive_seconds`, `num_ctx` and `thinking`. Timeouts are integers from 0 to 3600 seconds; 0 releases the model after each reply. Context values are 512 to 8192. Restart to apply changes. Client messages cannot override timeout or context settings. Keep `local-ai` as the default ID.

The new installer adds Small and Large presets to older configurations once, preserving the existing default model and secrets, with a private `config.before-text-presets.json` backup. Later reruns preserve edited presets. Downloads and native acceptance checks follow the configured models. The three default text downloads total roughly 31 GB; this is download size, not peak runtime memory. Large-model memory and performance still require validation on your Mac.

To upgrade an earlier installation, stop Local AI, extract this updated bundle and rerun the same installation command. Changed code/configuration invalidates the previous acceptance fingerprint. The installer runs generation checks again and stops if any configured model fails.

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
