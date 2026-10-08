# Local conversation mode

Implemented as a loopback microphone/playback interface to a real OpenCode session.
It uses the existing coordinator, specialist handoffs, tool budgets and native
permission system. This is a modular speech pipeline, with bounded turns and
interruptible playback, not a single speech-to-speech model.

## Start

1. Stop Local AI and the work agent, then rerun the updated installer. It adds
   pinned Parakeet and Silero assets to the private voice environment and
   load-checks VAD, STT and TTS. Existing reference voices remain intact.
2. Register `default` with **Configure Voice.command** if necessary. Qwen3-TTS
   1.7B Base requires a reference WAV and its exact transcript.
3. Start Local AI, select Normal or Max, and wait for Ready.
4. Open **Start Conversation.command**. Its private link opens at
   `http://127.0.0.1:8003`. Allow microphone access, select a registered voice,
   and press **Start conversation**. Keep the launcher Terminal open.
5. The default is push to talk. Hold the button, speak, then release. Select
   hands-free for automatic turn detection. You can also type messages.

This launcher owns the work-agent port, so close an existing work agent first.
It starts with an empty project copy. To use a selected project, run:

```sh
cd ~/LocalAI-Automated/control
.venv/bin/python work_agent.py --root ~/LocalAI-Automated --conversation --project /absolute/project/path
```

The existing project-copy exclusions and native Plan/Build restrictions apply.
Plan is the default. Build edits/commands still require approval; the voice UI
shows pending native permission details and offers **Allow once** or **Deny**.
The full OpenCode UI remains available on port 4096 with the session password
printed by the launcher. There is no automatic voice-based approval.

## Components and flow

| Component | Implementation |
|---|---|
| Capture | Browser AudioWorklet, PCM16 mono at 16 kHz, 192 ms batches; browser echo cancellation requested |
| Voice activity | Silero v6.2 ONNX on CPU, one thread; continuous 32 ms frame probabilities |
| Transcription | MLX Parakeet TDT 0.6B v3, pinned revision `ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15` |
| Captions | Re-decode the current utterance approximately every two seconds; provisional text never enters the agent session |
| End of turn | Sustained speech plus roughly 704 ms silence, or push-to-talk release; utterances bounded below 30 seconds |
| Agent | Native OpenCode session, coordinator and existing team plugin; native message updates polled every 300 ms |
| Text streaming | Ollama NDJSON to real OpenAI SSE deltas; structured tool calls validated and emitted once with stable IDs |
| Speech | Existing pinned Qwen3-TTS 1.7B Base on MLX, resident between turns; bounded phrases and incremental PCM |
| Playback | Browser AudioContext, at most roughly seven seconds queued by acknowledgement-based backpressure |
| Interruption | Stop scheduled audio immediately, invalidate response generation, abort native session, cancel active TTS |

Parakeet v3 covers 25 European languages. It does not cover every language that
Qwen TTS can speak. The current UI uses automatic recognition and TTS language
selection. It sends completed recognised utterances automatically, so check the
caption when proper names or precise commands matter; consequential tools retain
their normal approval requirements.

The gateway never sends reasoning tokens to playback. Spoken text receives light
Markdown/link cleanup, but this is not a rich document narrator. Long code blocks
are better read in the full work-agent interface.

## Memory and cancellation

Only the configured 4B coordinator at at most 8K context may run concurrently
with STT/TTS. All larger text profiles, media rendering and standalone `/speak`
jobs take exclusive model ownership. Before those jobs start, the gateway kills
and waits for resident STT/TTS processes, and waits for their readers to release
ownership. Afterward it unloads the larger text model before speech may reload.
The tiny CPU detector keeps listening during that work.

Speech interrupted by a larger-model job skips the incomplete phrase, reports
the pause, and resumes at the next phrase after the job. An utterance waiting for
STT retries that read-only transcription for up to one minute; it is submitted
to OpenCode only once. Other STT/model errors remain visible, without replaying
the user's request automatically.

Normal end-of-turn completion keeps idle speech models resident. Barge-in kills
an actively generating TTS process, so its next reply incurs a reload. Playback
stops immediately in the browser. Backend text cancellation is cooperative at
the next received Ollama chunk; prefill can delay that acknowledgement. The
executor retains ownership throughout. Native abort does not undo completed
edits, commands or media side effects.

MLX caches are limited to 256 MiB per process and cleared between audio jobs.
That is a cache limit, not a promise about total memory. Other apps, prompt/KV
memory and temporary inference allocations still count toward the Mini's 32 GB.
The installer does not raise OS memory limits. Hardware performance is unverified
in the authoring environment.

End conversation releases the audio workers. Lost browser heartbeats end the
conversation after about 15 seconds; the gateway has its own 20-second audio
lease timeout. Workers also exit if their gateway parent disappears. Resource
mode changes or a gateway restart stop the owning work agent as before.

## Local records and access

- Native session history stays in `work-agent/state` as before. Handoff records
  continue to use the existing ledger and project reports.
- `work-agent/state/conversation.jsonl` records user text, generated text,
  completed-playback phrase acknowledgements, errors, interruptions and timings.
  It rotates at about 5 MB with one previous file. These records are local
  plaintext, outside the encrypted vault; microphone PCM is not written to disk.
- A playback acknowledgement means the browser finished a scheduled buffer,
  not proof that the person heard it. Partial phrases are not marked fully
  played. The next native prompt includes a bounded delivery record so the
  assistant can distinguish generated text from confirmed completed playback.
- The private UI token is passed in the URL fragment and removed from browser
  history after loading. It is not the gateway key or native server password.
  API requests require it and an exact local Host/Origin. No CORS is enabled.
- Port 8003 is loopback-only and is not published by the existing remote/media
  routes. Refreshing the page requires reopening the private launcher link.

## Acceptance on the Mac

Run **Check Conversation.command** with Local AI ready, a registered default
voice and no active conversation. It synthesises a fixed sentence, measures
first audio/total synthesis time, transcribes the result, checks similarity and
VAD detection, then releases the audio models. Results go to
`conversation-check.json`; audio stays in memory. The timing is a cold-load
smoke check, not a conversational latency benchmark.

Then perform these interactive checks. They are deliberately recorded as
`not_run` in installer acceptance until checked on the actual machine:

1. Push-to-talk and hands-free: compare live/final captions with what you said.
2. Speak over a long answer: sound must stop promptly; no old audio or text may
   arrive in the new response. Check played versus generated log entries.
3. Test both headphones and speakers. If echo triggers false interruptions,
   use headphones or push to talk. Browser AEC is requested, not guaranteed.
4. Deny a proposed tool permission; verify it stays denied. Approve an intended
   Build edit once and inspect the project copy and native tool history.
5. Trigger an analyst/coder handoff and image/video work. Observe voice pause,
   model release and subsequent resumption. Video still requires Max.
6. Watch Activity Monitor memory pressure and swap during at least ten minutes
   of dialogue, including long context. Record warm turn latency and audible
   gaps; no target-Mac speed claim is made yet.
7. Close the tab and verify audio workers disappear; switch to Gaming and
   verify conversation stops. Test mic denial and an unavailable reference voice.

Automated authoring tests cover native API bridging with simulated responses,
stream delivery, permission/session scoping, stale-event rejection, playback
accounting, model exclusivity and VAD endpoint logic. The optional Playwright
test exercises the browser with a fake microphone and backend. These do not
replace the native acceptance checks above.

Primary interfaces checked against pinned sources:
[OpenCode 1.18.34 session API](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/server/routes/instance/httpapi/groups/session.ts),
[Parakeet MLX implementation](https://github.com/Blaizzy/mlx-audio/blob/200aac3c64e5140dbe0daa4570dcb129f0f7afc9/mlx_audio/stt/models/parakeet/parakeet.py),
[Silero ONNX wrapper](https://github.com/snakers4/silero-vad/blob/be95df9152c0d7618fa1edfeb296fc3dae32376f/src/silero_vad/utils_vad.py).
