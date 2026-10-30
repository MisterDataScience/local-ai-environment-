# Discord calls through Local AI

The main installer includes Discord. Local AI starts the bot automatically when
its foreground launcher is running and the gateway is ready in Normal or Max.
Join the private **local-ai** voice channel from Discord on your phone or computer.
The bot joins you, transcribes your speech locally, sends it to the existing
OpenCode coordinator and speaks with the registered Qwen3-TTS `default` voice.
This is a server voice channel, not a direct-message phone call.

## Defer bot and reference voice setup

If you want to try the local Captain before setting up voice calls, run the main
installer with `--defer-discord` (for example,
`/bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI.command" --defer-discord`).
The installer still prepares the Discord transport dependencies so the installed
`Connect Discord.command` can be used later, but it does not request a Discord
bot token, server invitation or reference WAV. On a fresh installation Discord
remains disabled; local Captain and ordinary chat are unaffected.

When you have a valid bot token and 3–30-second reference WAV with an exact
transcript, run `Connect Discord.command` to complete setup. On an upgrade,
`--defer-discord` leaves any already enabled Discord configuration unchanged.

## One-time setup

You use your ordinary Discord account to own a bot application; the bot does
not need a second ordinary user account. During installation:

1. Open the Developer Portal link printed by setup, create an application, open
   its Bot page and turn **Public Bot** off. Generate a bot token.
2. Paste the token into the installer's hidden local prompt. Never put it in a
   chat, issue or repository. macOS Keychain stores it; configuration contains
   account/channel identifiers, not the token.
3. Open the invite link printed by setup and add the bot to a Discord server
   you own. Create a server in Discord first if you do not have one.
4. Setup creates the private `local-ai` voice channel. If your `default` voice
   is not registered, supply a clean 3–30 second 16-bit PCM WAV and its exact
   transcript. Existing registered voice files are reused.

No Discord desktop app is required on the Mac mini. Keep the Mac awake and Local
AI running. Installing does not enable automatic startup at macOS login.
For token replacement or account repair, stop Local AI, run
`Connect Discord.command`, then start Local AI again.

## Call behavior

- Only the configured owner's audio is subscribed to. The bot disconnects if
  another member joins, or if the channel's checked permissions become public.
  Administrators can override Discord channel permissions; use your own private server.
- Local Silero voice detection confirms speech before interrupting the current
  answer. Utterances are limited to 28 seconds, with a 700 ms silence endpoint.
  While an utterance is transcribing/submitting, another utterance is not queued.
- The channel's text chat shows recognized speech, complete answers, status and
  **Plan**, **Build**, **Stop answer** and **Disconnect** buttons. Plan is the
  default for each new call. Disconnect stays disconnected until you leave and
  rejoin. Use headphones if the phone's echo cancellation feeds bot speech back.
- Native tool requests show their exact permission, patterns and metadata in a
  JSON attachment. Only you can choose **Allow once** or **Deny**, and only while
  that request is pending in this conversation. Switching to Build grants no
  blanket approval. Requests over the review bound can only be denied.
- Specialist and media jobs obey the existing gateway memory policy. Speech may
  pause during heavier work. A transcription refused during such work asks you
  to try again; there is no unbounded audio queue or extra always-loaded LLM.
- Image/video tools retain their existing saved output locations and links;
  the adapter does not automatically upload media files into Discord.
- Leaving the channel, changing resource modes or stopping Local AI cancels the
  call. Gaming disables the adapter. Normal/Max readiness allows it to restart.
  An already-running manual work-agent/conversation launcher takes precedence;
  Discord waits for its ports to be free.

## Privacy and records

Discord transports voice and stores posted text/attachments. Local inference
does not make the calling transport local-only. The bot uses only Guilds and
GuildVoiceStates intents, with no privileged Message Content intent. Its channel
creation permission is used by setup, not exposed as a model tool.

The token travels from Keychain to the adapter through a private stdin pipe,
not a command-line argument, environment variable or saved bootstrap file.
The conversation HTTP bridge stays authenticated on loopback. Models continue
to run through the existing harness permissions; this is not an OS sandbox.

Existing local session/handoff records are retained. Conversation records are
at `work-agent/state/conversation.jsonl`, with one rotated previous file. Discord
playback acknowledgements mean audio passed the packet-paced playback clock;
they do **not** prove the listener heard it. Interrupted, unsent phrases are not
acknowledged. Raw input audio is not saved by the adapter. Call text is also posted
to Discord. Adapter diagnostics are in `logs/discord.log`.

## Dependencies and required live check

Pinned: Node 24.21.0 (verified Darwin arm64 archive), discord.js 14.27.0,
@discordjs/voice 0.19.2 and opusscript 0.1.1, with a committed npm lockfile.
Installation disables npm lifecycle scripts and checks the Opus codec and
platform DAVE encryption library. Audio reception uses an interface Discord
has not officially documented; upstream changes can require an adapter update.

Authoring checks exercise a simulated call and actual codec/dependency loading.
They do not verify Discord's live voice network, the Mac Keychain or Apple GPU
performance. The installer records `discord-live-call: not_run` until you test:

1. Join `local-ai`; ask a question and hear your registered voice.
2. Interrupt mid-answer; confirm old audio stops and the next answer responds
   to the interruption. Check the posted transcript and local conversation log.
3. In Build, ask for a harmless file operation. Deny its first approval and
   confirm it does not run; retry and approve once. Check the actual file.
4. Leave/rejoin, use Disconnect, and change to Gaming. Confirm the bot leaves
   and speech workers release memory. Return to Normal and confirm reconnection.
5. Measure response latency and Activity Monitor memory pressure during normal
   speech and a specialist handoff on the 32 GB Mac.

Sources: [Discord voice library](https://discord.js.org/docs/packages/voice/main),
[Discord Developer Portal](https://discord.com/developers/applications),
[Node release archive](https://nodejs.org/dist/v24.21.0/).
