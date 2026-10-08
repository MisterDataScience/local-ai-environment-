# Local Qwen3-TTS speech and voice cloning

Added 2026-10-08. The installer downloads the MLX conversion of
**Qwen3-TTS-12Hz-1.7B-Base**, BF16, and installs a private MLX-Audio environment.
No external speech API is used. The model snapshot is approximately 4.54 GB;
download size is not peak running memory.

## First use

1. Stop Local AI and rerun the updated installer. Speech dependencies and weights
   are downloaded on your Mac, not bundled inside the small installer ZIP.
2. Open `Configure Voice.command` in `~/LocalAI-Automated`.
3. Use voice ID `default`, provide a clean 3–30 second mono/stereo, 16-bit PCM WAV
   sample, and enter the exact words spoken in that sample.
4. Start Local AI in Normal or Max mode. In ordinary chat, enter
   `/speak The bloody printer has broken again.`
5. Open the returned WAV link to listen or download.

The Base checkpoint has no preset speakers. A reference recording and transcript
are required for the supported cloning workflow. It does not implement the
CustomVoice preset speaker list or VoiceDesign instructions. Register further
samples under simple names such as `narrator`; existing IDs are never overwritten
by the helper. Use a new ID for another sample.

For a non-PCM reference, convert it first using an audio editor or ffmpeg, e.g.
`ffmpeg -i sample.mp3 -ac 1 -ar 24000 -c:a pcm_s16le sample.wav`.
Short, clean speech with an accurate transcript matters more than a long recording.

## Coordinator use

Plan and Build expose `local_speech` with required fields:

```json
{"prompt":"Exact words to speak.","voice":"default","language":"English"}
```

The coordinator can write narration then generate its audio, or use a named
registered voice. Native approval shows the wording and voice selection. Language
can be `auto`, English, Chinese, Japanese, Korean, German, French, Russian,
Portuguese, Spanish or Italian. The tool cannot supply arbitrary sample paths,
URLs, models or scripts. Coder/analyst/document cannot invoke speech tools.
Direct `/speak` uses the `default` voice and automatic language selection.

Speech counts towards the existing two-media-attempt limit per explicit user
turn, alongside images/video. Prompts/outcomes/timings are saved in the existing
project `.local-ai-media` reports. The coordinator cannot listen to the audio
or independently judge voice similarity. Failure/unknown outcomes are not
automatically retried.

## Memory, limits and storage

- Normal and Max allow speech. Gaming blocks it.
- Speech runs in the gateway's existing serial model queue, after ComfyUI stops
  and Ollama models unload. One worker process loads Qwen3-TTS, generates a WAV
  and exits before the next queued model operation. No always-running TTS server.
- Limit: 2,000 text characters, at most 120 seconds of generated audio, 1,500
  speech tokens per newline-delimited segment and a 10-minute worker timeout.
  Split longer narration into separate explicit requests. Limits can truncate
  or reject overly long output; do not assume every supplied word was spoken.
- Worker inference is offline, with cloud-provider keys excluded from its
  environment. Installation requires internet access for packages and weights.
- Generated audio is mono 24 kHz, 16-bit PCM WAV. In vault mode it is written
  directly through the descriptor-based atomic vault output API. There is no
  plaintext WAV fallback if the vault is unavailable. Otherwise it is saved in
  the same local media directory used by the gateway.
- Reference WAVs and their transcripts live in `voice-engine/voices` with private
  file permissions. They are plaintext outside the vault. The selected source
  recording is copied there; generation does not modify it.
- Debugging: `logs/speech.log`, `voice-engine/artifacts.json` and
  `voice-engine/dependencies.txt`. Existing remote media routes also serve WAVs.

The standalone `/speak` path provides text-to-speech and reference-voice cloning.
For microphone input, local transcription, automatic response playback and
interruption, use the separate [conversation mode](REALTIME-CONVERSATION.md).
Arbitrary recording-to-recording voice conversion is not implemented.

## Pinned sources and validation

- [MLX model](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16),
  revision `a6eb4f68e4b056f1215157bb696209bc82a6db48`.
- [MLX-Audio](https://github.com/Blaizzy/mlx-audio), source commit
  `200aac3c64e5140dbe0daa4570dcb129f0f7afc9`.
- [Original Qwen model](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base).

The installer records downloaded artifact hashes and installed dependency
versions, and checks native model loading before recording speech installation
as successful. Dependency versions are recorded after resolution; only the
MLX-Audio source and model revision are pinned here, not a complete dependency lock.
Installer hardware acceptance includes speech generation followed by text
reload when a default reference has already been registered. Otherwise the
report explicitly marks speech generation `not_run`; model loading alone is not
a voice-quality or performance test. Rerun the installer after registering a
voice to perform that check.

Local authoring tests use mocked MLX execution and cover routing, voice options,
permissions, worker isolation, output validation, serial handoffs and encrypted
output selection. Actual synthesis, similarity, speed and peak memory on the
32 GB Mac remain target-machine validation.
