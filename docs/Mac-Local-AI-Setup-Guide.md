# Local text, image and video AI on a 32GB Apple Silicon Mac

Historical manual baseline, prepared 5 October 2026. These steps describe the
original Qwen3/serial-gateway system, not the current Captain installer. For a
new installation or upgrade use [deployment](DEPLOYMENT.md) and check its package
status first. Keep the instructions below as historical reference; do not apply
them over an automated installation.

This baseline targets a single-user Apple M-series Mac with **32GB total unified
memory**, not an Intel Mac or a separate 32GB graphics card.

## Software chosen for you

| Job | Choice |
| --- | --- |
| Browser | Safari |
| Chat interface | Open WebUI, installed locally in its own Python 3.11 environment |
| Text backend | Ollama, native macOS application/command-line server |
| Text/reasoning/code model | `qwen3:14b`, the default Q4_K_M quantisation |
| Image/video backend | ComfyUI, manual native installation with PyTorch MPS |
| Image model | SDXL Base 1.0, one checkpoint, no refiner |
| Video model | LTX-Video 2B v0.9.5, full-precision checkpoint with FP16 T5 text encoder |
| Orchestrator | Supplied Python gateway, using explicit `/image` and `/video` commands |
| Package installation | Homebrew and uv |
| Video export | FFmpeg, producing an MP4 from ComfyUI's animated WebP |

The image and video models are conservative starting choices with native ComfyUI example workflows. They are not a claim to the best available visual quality. The older LTX model avoids beginning with the substantially larger LTX-2 family. The text model is approximately a 9.3GB download. Video also needs a separate roughly 9.79GB text encoder, in addition to the roughly 6.34GB checkpoint. File sizes are **not** peak running-memory requirements.

The gateway uses Python's standard HTTP server rather than FastAPI. Its single worker serialises all model requests. This is a small local application, not a production server.

Normal chat goes to Ollama. `/image DESCRIPTION` goes to SDXL. `/video DESCRIPTION` goes to LTX. Generated images appear in the chat; videos return a local MP4 link. The baseline does not include image understanding, attachment-conditioned image-to-video, automatic natural-language routing, tool execution, voice, RAG, or agentic coding. Coding means generating and explaining code in chat.

## 1. Check the Mac before installing anything

1. Click the Apple menu at the top left.
2. Open **About This Mac**.
3. The chip should say **Apple M1, M2, M3, M4, M5**, or an M-series Pro/Max/Ultra variant.
4. Check that Memory is **32GB or more**. A 32GB Mac has one shared memory pool, not 32GB dedicated to the GPU.
5. Open **System Settings > General > Software Update**. Use a current supported macOS release. Homebrew currently supports macOS 15 and newer; this guide assumes that or newer.
6. Open **System Settings > General > Storage**. Have at least **100GB free on the internal SSD** before starting. This is a planning allowance for models, environments, caches and outputs, not a measured installation total.
7. Connect the Mac to power. Close games, virtual machines and other memory-heavy applications.
8. Open **Activity Monitor**, click **Memory**, and keep it available during the first video test.

If the chip says Intel, stop here: the MPS route below does not apply. If the machine has less than 32GB, these model choices need revising. Do not change macOS GPU memory limits or disable PyTorch memory safeguards to force a failed render through.

## 2. Open Terminal and install Apple's command-line tools

1. Press **Command + Space**.
2. Type `Terminal`, then press Return.
3. Paste this command and press Return:

```bash
xcode-select --install
```

4. If an installation window appears, click Install and let it finish. If Terminal says the tools are already installed, continue.
5. Check that Git is available:

```bash
git --version
```

You should get a version number. Throughout this guide, paste code blocks into Terminal, one block at a time. Wait until the prompt returns before pasting the next. Do not type the ``` marks. Commands prefixed with `~/` use your home folder.

## 3. Install Homebrew, then uv and FFmpeg

Use the official Homebrew installer:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Read the displayed installer actions, press Return when instructed, and enter your Mac login password if requested. Terminal will not display password characters as you type.

After installation, put Homebrew on this Terminal's path:

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Run the following **once** to make that path available to future Terminal windows:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
```

Install the two tools:

```bash
brew install uv ffmpeg
```

Verify:

```bash
uv --version
ffmpeg -version
```

Both commands should print version information. uv installs Python and isolated environments; FFmpeg exports videos. You do not need Docker, CUDA, NVIDIA drivers, Anaconda, a second chat UI, or a ComfyUI extension for this setup.

## 4. Download this setup bundle and place it correctly

1. Download **mac-local-ai-setup.zip** from the accompanying answer.
2. Put the ZIP in your Mac's **Downloads** folder.
3. If Safari automatically extracted it, use the extracted `mac-local-ai` folder instead of the ZIP commands below.
4. In Terminal, create the parent directory:

```bash
mkdir -p ~/LocalAI
```

5. Extract and rename the bundle:

```bash
unzip ~/Downloads/mac-local-ai-setup.zip -d ~/LocalAI
mv ~/LocalAI/mac-local-ai ~/LocalAI/control
```

If Safari already extracted it, use Finder to move `mac-local-ai` into your home folder's `LocalAI` folder, then rename it `control`.

6. Verify:

```bash
ls ~/LocalAI/control
```

You should see `gateway.py`, `initialise.py`, `README.md`, `workflows`, `tests`, and the `.command` launchers.

The setup must live in `~/LocalAI`, outside iCloud Drive or Dropbox. A local directory avoids synchronising large models and live databases. Do not repeat the move command over an existing installation.

## 5. Install Ollama

1. In Safari, open https://ollama.com/download/mac.
2. Download the macOS application.
3. Open the downloaded installer/disk image and move Ollama to **Applications** as instructed.
4. Open Ollama once.
5. Allow it to install its command-line link if prompted.
6. Confirm the command works:

```bash
ollama --version
```

7. Quit Ollama using its menu-bar icon. We will run one explicit Ollama server with known settings instead of relying on the app's startup environment.
8. Disable Ollama's automatic startup in its settings or **System Settings > General > Login Items** if it has enabled it.

Do not run the app server and the supplied server launcher at the same time.

## 6. Make the launchers executable and start Ollama

```bash
chmod +x ~/LocalAI/control/*.command
```

Start the backend in this Terminal:

```bash
~/LocalAI/control/start-ollama.command
```

Leave this window open. The launcher limits Ollama to one loaded model, one parallel request and an 8,192-token default context. It binds to `127.0.0.1`, so this is a local service.

If the log says the port is already in use, quit the Ollama app and retry. Do not start a second server.

Open a **new Terminal window** with Command + N for the next steps.

## 7. Download and test the text model

```bash
ollama pull qwen3:14b
```

Wait for the download to finish. Then test it:

```bash
ollama run qwen3:14b
```

At Ollama's prompt type:

```text
Explain a Python list in three sentences. /no_think
```

Wait for a reply, then enter `/bye` to return to Terminal.

Unload the test model:

```bash
ollama stop qwen3:14b
ollama ps
```

`ollama ps` should show its headings with no model rows. This confirms Ollama reports no loaded models; it is not a measurement of every byte of macOS GPU memory. Do not start ComfyUI while the text model remains loaded.

## 8. Install ComfyUI in its own environment

```bash
cd ~/LocalAI
git clone https://github.com/Comfy-Org/ComfyUI.git
```

Create its environment and install dependencies:

```bash
cd ~/LocalAI/ComfyUI
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python torch torchvision torchaudio
uv pip install --python .venv/bin/python -r requirements.txt
```

Use the regular macOS PyTorch packages. MPS is Apple's GPU backend; CUDA packages are for NVIDIA and do not belong in this installation.

Check Python's architecture and MPS:

```bash
.venv/bin/python -c 'import platform, torch; print("Architecture:", platform.machine()); print("MPS built:", torch.backends.mps.is_built()); print("MPS available:", torch.backends.mps.is_available())'
```

Expected results: `arm64`, `MPS built: True`, and `MPS available: True`. Do not proceed with GPU rendering if MPS is unavailable. Check macOS support and whether Terminal is running through Rosetta.

Record the working installation:

```bash
git rev-parse HEAD > ../comfy-commit.txt
uv pip freeze --python .venv/bin/python > ../comfy-installed.txt
```

## 9. Download the image model into the exact folder

```bash
mkdir -p ~/LocalAI/ComfyUI/models/checkpoints
curl -fL --retry 3 -C - -o ~/LocalAI/ComfyUI/models/checkpoints/sd_xl_base_1.0.safetensors 'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors'
```

This is one approximately 6.94GB checkpoint. Keep the filename unchanged: the supplied image workflow refers to it. Download this individual file, not the whole Hugging Face repository. The initial workflow generates a single 768 x 768 image using 24 steps.

## 10. Download the video model and its text encoder

```bash
mkdir -p ~/LocalAI/ComfyUI/models/text_encoders
curl -fL --retry 3 -C - -o ~/LocalAI/ComfyUI/models/checkpoints/ltx-video-2b-v0.9.5.safetensors 'https://huggingface.co/Lightricks/LTX-Video/resolve/main/ltx-video-2b-v0.9.5.safetensors'
```

Then download the encoder:

```bash
curl -fL --retry 3 -C - -o ~/LocalAI/ComfyUI/models/text_encoders/t5xxl_fp16.safetensors 'https://huggingface.co/Comfy-Org/mochi_preview_repackaged/resolve/main/split_files/text_encoders/t5xxl_fp16.safetensors'
```

Both files are required. Keep the names unchanged. Use the FP16 encoder specified here, not an FP8 alternative. Verify the two files against the publisher's checksums:

```bash
shasum -a 256 ~/LocalAI/ComfyUI/models/checkpoints/ltx-video-2b-v0.9.5.safetensors
shasum -a 256 ~/LocalAI/ComfyUI/models/text_encoders/t5xxl_fp16.safetensors
```

Expected hashes, in the same order:

```text
720d15c9f19f7d0f6b2a92bbbc34410e2cfb2f6856a100b38f734fbf973d4adf
6e480b09fae049a72d2a8c5fbccb8d3e92febeb233bbe9dfe7256958a9167635
```

The supplied video workflow starts at **512 x 320, 17 frames, 12fps, one clip**. That is a roughly 1.4-second motion test. It uses LTX's native ComfyUI nodes and saves animated WebP, which the gateway converts into MP4. This is not an audio-generation model.

## 11. Install the gateway and create its local configuration

```bash
cd ~/LocalAI/control
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python initialise.py
```

The final command creates `config.json` and displays two values:

- Connection URL: `http://127.0.0.1:8000/v1`
- A randomly generated API key.

Keep the key for step 15. It is a **local gateway key**, not an OpenAI account/API key. Re-running `initialise.py` prints the same stored key without replacing the configuration.

Run the code checks:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The tests check gateway sequencing and failure handling. They do not test GPU inference.

## 12. Validate the workflows against your installed ComfyUI

With Ollama's server still running and the gateway not yet running:

```bash
cd ~/LocalAI/control
.venv/bin/python check-workflows.py
```

This command unloads Ollama, briefly starts ComfyUI, checks both workflows against ComfyUI's installed node/input/model lists, then stops ComfyUI. It should report that image and video schemas validated. It does not render or prove memory fit.

If a node or model filename is missing, resolve that error before continuing. You do not need to import or hand-wire workflows in the ComfyUI interface: the included files are API workflows ready for the gateway.

## 13. Install Open WebUI in a separate Python 3.11 environment

```bash
mkdir -p ~/LocalAI/webui/data
cd ~/LocalAI/webui
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python open-webui
```

Python 3.11 is chosen because Open WebUI documents it as its most heavily tested Python route. Do not install WebUI into ComfyUI's environment.

Record versions:

```bash
uv pip freeze --python .venv/bin/python > webui-installed.txt
```

Chat data is deliberately stored in `~/LocalAI/webui/data`, outside the disposable environment.

## 14. Start the gateway and Open WebUI

Open a new Terminal window and run:

```bash
~/LocalAI/control/start-gateway.command
```

Leave it open. It should report a gateway listening on `127.0.0.1:8000`.

Open another Terminal window and run:

```bash
~/LocalAI/control/start-webui.command
```

Leave that open too. Wait for WebUI startup to finish.

You now have three Terminal windows: Ollama, gateway and Open WebUI. ComfyUI is **not** kept running in a fourth window: the gateway starts and stops it on demand.

In Safari open:

```text
http://127.0.0.1:8080
```

Bookmark it as **Local AI**.

## 15. Connect Open WebUI to the gateway

1. Create the first local WebUI account if requested. It becomes the administrator account. This is stored locally.
2. Open your profile/avatar menu.
3. Open **Admin Panel > Settings > Connections**. Some versions label the route **Settings > Admin > Connections**.
4. Keep direct **Ollama connections disabled**. The supplied launcher disables the Ollama connection type, but verify the saved UI settings too.
5. In **OpenAI API Connections**, click **+** to add a connection.
6. Set the URL to **`http://127.0.0.1:8000/v1`**.
7. Paste the local API key printed in step 11.
8. Save and refresh the model list.
9. If this version requires a Model IDs entry, enter **`local-ai`**.
10. Start a new chat and select **`local-ai`** from the model selector.
11. In WebUI's task/model settings, turn off automatic title generation, follow-up generation and tag generation for the initial setup. These background jobs can trigger extra text-model calls after a render.
12. Leave image-engine integration, tools, web search, voice, knowledge/RAG and document extraction disabled for the baseline. The gateway handles `/image` and `/video` in ordinary chat; WebUI's separate image-generation integration is not needed.

The UI speaks an OpenAI-compatible protocol to your own gateway. Requests do not go to OpenAI. You do not need a paid API account.

## 16. Test text, image, text, video, then text

Perform these in a new `local-ai` chat, one at a time. Wait for each to finish.

**A. Text**

```text
Write a Python function that returns the mean of a non-empty list of numbers. Explain how it works.
```

Expected: a text answer. The default gateway disables Qwen's thinking output for responsiveness. To enable reasoning mode later, stop the gateway, change `"thinking": false` to `true` in `control/config.json`, then restart it. Context remains capped at 8,192 tokens and output at 2,048 tokens in this starter configuration.

**B. Image**

```text
/image A realistic photograph of a red racing car parked beside a Scottish loch, misty mountains in the background, soft morning light, no text.
```

Expected: the text model unloads, ComfyUI starts, an image appears, and ComfyUI exits. While rendering, `ollama ps` in a separate Terminal should show no model rows. On completion, open the image download link.

**C. Text after the image**

```text
Explain the difference between correlation and causation in four sentences.
```

Expected: Ollama reloads and replies. The gateway does not interpret the image; this is a text-memory handoff test.

**D. Video**

```text
/video A fixed camera watches a small red racing car drive slowly from left to right along a quiet road beside a Scottish loch. The wheels turn naturally. Light mist moves over the water. Soft morning light, realistic colours, stable camera, no text or logos.
```

Expected: a short video download link. Click it to play/download the MP4. It is silent. The first run can take substantially longer than an image; no timing guarantee is made without your chip and a measured run.

Watch Activity Monitor's **Memory Pressure** graph. If pressure stays red, swap grows rapidly, or the machine becomes unresponsive, stop the render rather than retrying a larger clip. Read troubleshooting below.

**E. Text after video**

```text
What does an isolated Python environment do?
```

Expected: another text reply, with the ComfyUI process already stopped. Passing this sequence verifies the baseline on your hardware. Do not declare the system working from the software tests alone.

## 17. The exact model-swapping sequence

The gateway executes one request at a time, including requests from multiple browser tabs:

1. Classify the latest user message: `/image`, `/video`, or ordinary text.
2. Wait for the prior gateway job to finish.
3. Before text: ensure no gateway-owned ComfyUI process remains and port 8188 is free.
4. Run the Ollama text request. Keep the text model loaded for up to five minutes for successive text chats.
5. Before image/video: request unload for every model reported by Ollama's `/api/ps`, using `/api/generate` with `keep_alive: 0`.
6. Poll `/api/ps` until Ollama reports an empty loaded-model list. If it does not confirm unload within the timeout, fail the job without starting ComfyUI.
7. Start a fresh ComfyUI process and wait for its local API to become ready.
8. Replace the positive-prompt marker and seed in the selected workflow.
9. Submit the workflow and poll its history until completion or failure.
10. Copy the generated output into the gateway's `media` folder.
11. Stop ComfyUI's process group and wait for process exit and port closure, including after render errors and timeouts.
12. Convert video frames into MP4 on the CPU.
13. Return a local image/video link to WebUI.
14. Load Ollama again only when the next text request needs it.

This is deliberately a full ComfyUI process restart for each visual job. CPU offloading alone would not free the Mac's shared memory pool. Process exit also releases ComfyUI's MPS allocator caches. `/api/ps` and process exit are lifecycle checks; macOS memory accounting can settle afterwards.

The gateway sends streaming keep-alive messages while it waits, then returns the completed answer. Text is buffered rather than displayed token by token. Closing a chat tab does not abort a job: it finishes or times out, then cleans up, keeping the model sequence intact. Four requests may be queued; further requests are rejected.

The sequencing assumes you use the gateway exclusively. A separate Ollama client can load a model behind its back. Do not run direct Ollama chats or manually queue ComfyUI jobs while this system is in use.

## 18. Daily startup and shutdown

**Startup**

1. Open Terminal.
2. Run `~/LocalAI/control/start-ollama.command` in the first window.
3. Run `~/LocalAI/control/start-gateway.command` in a second window.
4. Run `~/LocalAI/control/start-webui.command` in a third window.
5. Open the Safari **Local AI** bookmark.
6. Select `local-ai` and chat. Use the exact `/image` or `/video` prefix for visual generation.

After initial setup, Finder can open these executable `.command` files as launchers. If macOS refuses a downloaded script, use the Terminal command shown above or the normal **Open** action after reviewing it; do not disable Gatekeeper globally.

**Shutdown**

1. Let active renders finish.
2. Press **Control + C** in the Open WebUI window.
3. Press **Control + C** in the gateway window. It waits for queued jobs and then cleans up its ComfyUI process. Do not force-close it during cleanup.
4. Run `ollama stop qwen3:14b` in another Terminal if the model remains loaded.
5. Press **Control + C** in the Ollama server window.

## 19. Increase video length only after the small test works

The baseline is 512 x 320, 17 frames, 12fps. Open `~/LocalAI/control/workflows/video.json` in a plain-text editor. Find node `"70"`, then its `"length": 17` entry.

1. Try **33** frames first, about 2.75 seconds at 12fps.
2. Then try **49** frames, about 4.1 seconds.
3. Keep width 512, height 320 and batch size 1 while establishing the memory limit.
4. Keep frame counts in the `8n + 1` pattern for this workflow.
5. The gateway reads the workflow fresh per render, so saving the file is enough.

Do not raise duration and resolution together. Raising resolution increases intermediate tensors as well as output size. A 32GB Mac is not equivalent to a 32GB NVIDIA GPU plus a separate system-memory pool.

## 20. Troubleshooting

| Symptom | Action |
| --- | --- |
| `brew: command not found` | Run `eval "$(/opt/homebrew/bin/brew shellenv)"` in that Terminal. |
| `ollama: command not found` | Reopen the Ollama app once and allow its CLI setup; quit the app before starting the supplied server. |
| Ollama port already in use | Quit the menu-bar app or the previous server. Start only one server. |
| Gateway refuses port 8188 | A manual or orphaned ComfyUI process is still running. Stop that specific process before restarting the gateway. |
| `MPS available: False` | Check Apple Silicon, supported macOS and native arm64 Python; do not install CUDA. |
| WebUI shows no `local-ai` model | Confirm gateway startup, URL including `/v1`, API key, and saved connection toggle. |
| `401` | Reprint the key with `.venv/bin/python initialise.py` in `control`, then update the connection. |
| Model checkpoint missing | Confirm the exact filenames and directories from steps 9-10; run `check-workflows.py` with the gateway stopped. |
| Missing node or input-schema error | The current ComfyUI API differs from the supplied graph. Stop and inspect the named node; use the official workflow linked below and export it in API format. Keep `__LOCAL_AI_PROMPT__` in its positive prompt field. |
| Render failed or timed out | Read `~/LocalAI/control/logs/comfy.log` and the gateway Terminal. The gateway stops its renderer before allowing another request. |
| MPS operator unsupported | The launcher already enables PyTorch's supported CPU fallback. Some operators still need a workflow/backend adjustment; an error here is not solved by adding CUDA. |
| Image/video is black or contains NaNs | Stop. Inspect dtype/MPS errors in the log. Do not assume a downloaded checkpoint or model choice proves MPS numerical compatibility on every chip. |
| Video memory failure | Restore 17 frames; try width 384, height 256, batch size 1, and close memory-heavy apps. If the minimal test still fails, this video configuration is not validated on that Mac. |
| A request appears stuck | Check `/health` and the gateway's state; video can take much longer than text. The render timeout is one hour, configurable in `config.json`. |
| MP4 conversion fails | Check `ffmpeg -version`. The original animated WebP remains in `control/media`. |
| A chat tab was closed mid-job | Wait for the job/timeout. It keeps the single worker until cleanup rather than releasing the queue while the renderer still owns memory. |

Useful read-only checks:

```bash
curl http://127.0.0.1:8000/health
ollama ps
lsof -nP -iTCP:8188 -sTCP:LISTEN
tail -n 60 ~/LocalAI/control/logs/comfy.log
```

If a ComfyUI process survived a forced shutdown, `lsof` shows its PID. Confirm it is the Python command from your `~/LocalAI/ComfyUI` installation, then terminate **that PID** in Activity Monitor. Avoid broad `killall python` commands that could stop unrelated work.

## 21. Backups and updates

Back up `control/config.json`, `control/workflows`, `control/media` and `webui/data` using Time Machine. Stop the services before manually copying the WebUI database. Model files can be re-downloaded; generated files and chat histories deserve backup.

After acceptance tests pass, save version records rather than updating mid-session:

```bash
cd ~/LocalAI/control
uv pip freeze --python .venv/bin/python > gateway-installed.txt
ollama --version > ollama-version.txt
ollama list > ollama-models.txt
```

For later updates, stop the system, back up the data, update one component, then repeat step 16. Updating ComfyUI can change node names and schemas. Do not auto-update everything at once.

Everything binds to loopback on this Mac. No LAN/iPad access or cloud inference is configured. Installation and model downloads need internet; prompts go to the local services. WebUI may perform version/model checks unless separately configured for offline operation, so this guide does not claim an air-gapped installation.

## Sources and validation limits

Primary documentation checked for this guide:

- Ollama macOS installation and Apple Silicon support: https://docs.ollama.com/macos
- Ollama API and unload behaviour: https://docs.ollama.com/api/chat, https://docs.ollama.com/api/generate, https://docs.ollama.com/api/ps
- Qwen3 14B model and quantisation: https://ollama.com/library/qwen3:14b
- Open WebUI Python installation and supported Python versions: https://docs.openwebui.com/getting-started/quick-start/
- OpenAI-compatible connection: https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/
- ComfyUI native installation: https://docs.comfy.org/installation/manual_install
- PyTorch MPS support: https://docs.pytorch.org/docs/stable/notes/mps.html
- SDXL native examples: https://comfyanonymous.github.io/ComfyUI_examples/sdxl/
- LTX native examples and model-file locations: https://comfyanonymous.github.io/ComfyUI_examples/ltxv/
- Official LTX reference workflow, adapted to smaller dimensions/frame count: https://comfyanonymous.github.io/ComfyUI_examples/ltxv/ltxv_text_to_video_0.9.5.json
- Homebrew: https://brew.sh/
- uv: https://docs.astral.sh/uv/getting-started/installation/

The supplied gateway has been tested with simulated backend calls for serialization, routing, unload-before-start, and failure cleanup. No Apple GPU or model weights were available in the authoring environment. End-to-end WebUI rendering, MPS numerical behaviour, peak memory and generation speed remain subject to the checks on your Mac. The preflight script catches node-schema and filename incompatibilities before you render; it is not a GPU benchmark.
