# Gaming, Normal and Max

Run Local AI, then open `~/LocalAI-Automated/AI Modes.command` on the Mac.
Choose a mode and press Apply. Wait for **Ready**, then refresh Open WebUI and
choose an available text preset. The setting applies globally, including chats
from phones, tablets and Windows devices. The selector is a separate local page,
not an Open WebUI plugin or an extra model menu entry. Remote devices use the
selected mode but do not expose the mode-control page through the media listener.

| Mode | Eligible text models | Images | Video |
|---|---|---|---|
| Gaming | Qwen3.5 4B coordinator profiles; retained legacy Qwen3 4B | Blocked | Blocked |
| Normal | All validated team profiles; retained legacy Qwen3 4B/14B | Available | Blocked |
| Max | All configured text presets | Available | Available |

VPN search, page reading, GitHub and encrypted workspace tools remain available
subject to their own setup, account permissions and vault/network state.
Normal caps output at 4,096 tokens; Max caps it at 8,192. Team profiles use 8K coordinator, 32K analyst/document and 16K coder contexts
outside Gaming. Custom smaller contexts also cap output
at half their context; client requests may ask for shorter replies. Native
memory validation on the intended 32 GB M6 Mac mini remains required.

Gaming caps context at 4,096 tokens, output at 1,024 tokens, thinking off, and idle
residency at 120 seconds. These are enforced request/model limits, **not an OS RAM
quota** or a guarantee of game performance. macOS, Docker, WebUI and games share
unified memory. Native memory and game-performance measurements remain necessary.

## Switching and persistence

The gateway immediately closes admission to inference and invalidates queued
requests when a switch is accepted. An active render is interrupted at its next
poll and its ComfyUI process is stopped. An already-running Ollama text call may
finish or reach its existing timeout before unloading can complete. The UI says
Switching throughout; do not interpret selection alone as memory being free.
When Ready appears, ComfyUI is stopped and Ollama has confirmed no loaded models.
No replacement model is preloaded. Its first eligible request loads it.

If cleanup fails, all inference stays blocked and the selector reports an error.
Retry Apply after fixing the backend, or restart Local AI. The gateway repeats
cleanup on startup before reporting healthy. The selected mode is saved privately
in `control/resource-mode.json`, separate from credentials, and survives restarts.
Malformed saved mode state stops startup rather than silently allowing Max.

The initial mode is **Max** to preserve existing installations' capabilities and
allow the installer's full model/image/video acceptance sequence. Select Gaming
or Normal afterwards. A rerun requiring full hardware acceptance refuses to run
outside Max; it never silently overrides Gaming. Switch to Max and stop Local AI
before rerunning those tests.

## Enforcement boundary

The gateway filters `/v1/models`, checks incoming requests, checks again when
queued work starts, and checks before text inference. Selecting a cached or old
large-model entry in Open WebUI cannot bypass Gaming. Restrictions use actual
Ollama model tags, not merely a preset called Small. Custom model tags need Max
until explicitly supported by the policy. Ordinary chat and model tool calls
cannot change the mode through the advertised tool integrations.

The authenticated mode endpoint is `GET/POST /control/mode`. It is not advertised
as a model tool. The local launcher passes the existing gateway key in a URL
fragment, removed immediately by the page and held only in memory. No third-party
page resources or persistent browser credential storage are used. The media-only
listener rejects control endpoints, even with a gateway credential.

This policy controls requests through this gateway. It does not sandbox direct
Ollama/ComfyUI use, arbitrary Python plugins, OS commands, other applications or
other administrators. Use the bundled services through Open WebUI for enforcement.

## Verification

Authoring tests cover model/media blocking, tag-based eligibility, inference
limits, persisted mode, queue invalidation, active-render interruption, unload
failure recovery, authenticated HTTP controls, model-list filtering and isolation
from the media listener. On the Mac additionally verify native browser selection,
Open WebUI refresh behaviour, real Ollama unloading, MPS release and game memory.

