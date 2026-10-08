# Coordinator image and video generation

Speech update: `local_speech` now shares this backend queue and media-attempt
budget. See [VOICE-GENERATION.md](VOICE-GENERATION.md) for reference registration,
the exact Qwen3-TTS model, privacy/storage and audio limits.

Implemented 2026-10-08. The OpenCode Plan and Build coordinators expose
`local_image` and `local_video`. Each takes one text `prompt` (1–4,000 characters).
Example: "Write a short story and generate an illustration of its opening."
The coordinator writes the text, calls the image tool and returns the asset link.
Native permission requests show the proposed media prompt before submission.

These tools call the existing authenticated loopback gateway using the same
`/image` and `/video` routes as direct chat commands. They do not create a second
generation engine or delegate to another conversational model. Direct commands
remain available through the original chat interface.

- Images require Normal or Max. Video requires Max. Gaming blocks both.
- Resource mode changes require restarting the work agent. The backend checks
  the gateway instance/mode epoch at submission and again before queued work.
- The existing single-worker queue controls model loading. Text models unload
  before rendering; ComfyUI stops before text work resumes.
- At most two media attempts per explicit user turn, separate from the two
  specialist attempts. No automatic retries. Denied approvals consume no attempt.
- Only native top-level Plan/Build sessions can execute these tools. Coder,
  analyst and document sessions cannot invoke them through the policy.
- Prompts cannot select arbitrary workflows, checkpoints, filesystem paths,
  resolutions or URLs. Installed workflow settings remain in control.
- The coordinator returns the backend's exact asset links. It cannot inspect
  generated pixels and must not claim visual verification.

## Debugging and interruption

The persistent team ledger records media reservations, prompts and status before
submission. Completed/failed returns are written to `.local-ai-media/*.json` in
the project copy, including start/end times, elapsed seconds and asset links.
These local plaintext records do not duplicate image/video files. Project import
skips old media-report directories. Generated assets retain the backend's normal
storage behavior, including encrypted vault media when configured.

After interruption/restart, a reserved attempt remains consumed and is marked
interrupted; the ledger still has its prompt. A final report may not exist if
the process stopped before writing it. A lost connection or cancelled OpenCode
request does not prove backend generation stopped. Check backend status and
existing outputs before explicitly requesting another attempt. The tool's request
timeout is 70 minutes; the existing renderer timeout remains configured separately.

## Model decision

Reviewed on 2026-10-08. Keep SDXL Base 1.0 and LTX-Video 2B v0.9.5 as installer
defaults for this integration. This is a compatibility decision, not a claim
that they are the best available media models. No new model downloads were added.

| Candidate | What was verified | Decision |
| --- | --- | --- |
| [Z-Image-Turbo abliterated Qwen3 4B encoder](https://huggingface.co/BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1) | Community card describes a modified encoder and quantized files, not a complete image generator. | Candidate for a separate Z-Image workflow evaluation; not a drop-in SDXL checkpoint. |
| [FLUX.2 klein abliterated encoder](https://huggingface.co/PinoCookie/Flux.2-klein-4B-abliterated-text-encoder) | Community card targets the Qwen3 encoder and names FLUX.2-klein-base-4B. | Needs an exact compatible base-model/workflow pairing; do not assume compatibility with the distilled checkpoint. |
| [FLUX.2 klein 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) | Official compact generation/editing model; published GPU figures are not a 32 GB Mac benchmark. | Useful non-abliterated comparison when evaluating a replacement. |
| [Wan2.1 T2V 1.3B](https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B) | Official smaller video model. | Possible future comparison, not an abliterated or validated replacement for this Mac workflow. |

The review did not establish a suitable, verified abliterated video replacement.
Publisher refusal/representation measurements are not proof of improved visual
quality. Encoder size alone does not describe the memory of the diffusion model,
VAE, activations and full workflow. A replacement needs pinned artifact hashes,
compatible ComfyUI nodes, repeatable prompt comparisons, measured peak memory,
latency and unload/reload checks on the target Mac before becoming a default.

## Validation boundary

Local tests cover native identity/permission requests, successful image/video
submission, mode rejection, budgets, failure records and the existing gateway
queue. The pinned OpenCode v1.18.34 registry supports plugin tools with JSON
Schema arguments; the tools also validate inputs themselves. Startup verifies
effective coordinator media approval permissions. Actual native model tool
selection, OpenCode UI asset rendering and Apple GPU performance remain target-Mac
acceptance work.
