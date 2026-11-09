# LOCAL AI installer

Release: `2026-11-09-mac-native-recovery-1`.

Start with `Install LOCAL AI Core.command`. The older `Install Local AI.command`
and MiniCPM-named launcher use the same core-first route. Core installs Captain
and ordinary chat, with thinking enabled, then checks real specialist handoffs,
worker retirement and conversation recovery across compaction before startup.

Native Apple Silicon, macOS 15+, 32 GB memory, Apple Command Line Tools and
35 GB free space are required. Core asks for no reference WAV, Discord token,
vault password, Docker licence, Proton key, Tailscale login or GitHub credential.

Extract the archive. Stop an existing Local AI instance, wait for its Terminal
shell prompt, then run the launcher through Terminal:

```bash
/bin/bash "$HOME/Downloads/mac-local-ai-installer/Install LOCAL AI Core.command"
```

Use the actual extraction path if different. The scripts are unsigned. See the
[macOS approval steps](docs/MODULAR-INSTALLER.md#macos-blocks-a-downloaded-launcher).
No quarantine attributes or Gatekeeper settings are changed by this package.

Captain is at `http://127.0.0.1:4096`; ordinary chat is at
`http://127.0.0.1:8081`. `Open Captain.command` checks readiness and displays the
local Captain credentials. Keep the running supervisor Terminal open. Use a
new Terminal window for other shell commands. Right Control+C sends the Mac
interrupt under Jump Desktop's default Windows-to-Mac mapping.

Use the named optional installers when their inputs are ready.
`Install Everything.command` runs those same feature modules; each keeps its
own acceptance state. `Check LOCAL AI Setup.command` lists feature status and
the next installer. The Synod and studios need accepted encrypted workspace
storage and the existing Village permission checks.

`Check Captain Conversation.command` checks a running Captain in one new,
tool-denied test session. It verifies that completed replies stay stopped and
an unanswered genuine request resumes correctly through automatic compaction.
Its report is `logs/native-acceptance/conversation-repair-probe.json`. This scoped
check does not replace installation or optional-feature acceptance.

The repaired installed copy passed that check on the owner's Mac. Local source
tests and exact ZIP checks are recorded in VALIDATION.txt and
[release validation](docs/RELEASE-VALIDATION.md). This freshly rebuilt archive
has not itself been installed on the owner's Mac. GPU throughput, optional
audio/media/network features and physical reboot checks retain their own scope.

Existing models, chats, credentials and vaults are retained during upgrades.
The archive contains no model weights or private owner data.
