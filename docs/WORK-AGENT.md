# Work agent: upstream OpenCode

The installer includes the existing **OpenCode 1.18.34** application. It does not
implement another agent loop, editor, shell tool, permission UI or coding frontend.
Our integration installs its official Apple Silicon binary, provides an
OpenAI-compatible provider configuration and launches its existing web interface.
The release ZIP is SHA-256 pinned, checked before extraction, and only the binary
is extracted. Auto-update is disabled so compatibility changes are deliberate.

## Daily use

1. Start Local AI normally. Select **Normal** or **Max** and wait for Ready.
2. Open `~/LocalAI-Automated/Start Work Agent.command`.
3. Enter a local project folder to copy, or press Enter for an empty project.
   Source projects are not edited. The new work directory is printed in Terminal.
4. OpenCode opens its own browser UI at `http://127.0.0.1:4096`. Log in as
   `opencode` using the random session password printed in that Terminal.
5. It starts in OpenCode's Plan agent. Describe the task and review its plan.
   Switch to its Build agent when ready to edit. File changes and shell commands
   use OpenCode's own approval prompts. Ask it to run the relevant tests and show
   the resulting diff, rather than treating its answer as proof of correctness.
6. Keep the launcher Terminal open. Control+C stops its process group. Your project
   copy and OpenCode session data are preserved. The native project/session UI can
   reopen an existing project copy on a subsequent run; a new launcher import
   itself creates a fresh copy rather than overwriting earlier work.

This is a separate work interface, not an embedded switch inside Open WebUI.
This release exposes it only on the Mac's loopback address. Existing Tailscale
chat/media routes do not expose OpenCode to your other devices.

## Model and mode integration

OpenCode calls `http://127.0.0.1:8001/v1` through the existing gateway. It does not
connect directly to Ollama or ComfyUI. Only the custom local provider is enabled;
no paid/cloud model credentials or GitHub PAT are passed to the process.
The initial model is the existing Everyday preset, usually Qwen3 14B. Available
model entries and context limits come from the current eligible presets.
Normal and Max restrictions still apply server-side to every inference request.
Model selection does not load weights until requested.

The launcher refuses Gaming or a pending/failed switch. It checks mode status
once per second and stops its OpenCode process group on a mode switch or backend
loss. This is not an OS resource quota; already-dispatched or detached commands
are not guaranteed to stop. Never approve a background daemon or resource-heavy
command on the assumption that Gaming Mode sandboxes it.

The gateway now returns Ollama's actual prompt/completion token counts when
provided, including the final SSE chunk. This supports client context accounting.
It still buffers the complete response: OpenCode's Stop button does not guarantee
immediate cancellation of an already-running Ollama request. Existing handoff
and unload rules remain in force.

The current 4K/8K contexts and local model tool reliability are constraints. Start
with small, well-scoped tasks. OpenCode's automatic compaction is enabled with a
2,048-token buffer; it does not make a small context unlimited or guarantee that
all tool schemas fit. Real local-model task performance remains unverified.

## Workspace, credentials and execution boundaries

Copies live in `~/LocalAI-Automated/work-agent/projects/`; sessions, configuration
and caches use separate XDG directories under `work-agent/state/`. These are local
plaintext storage, outside the Cryptomator vault. They are not automatically
included in the WebUI backup. Use FileVault for local disk protection; keep
sensitive vault-only documents out of this harness until a dedicated encrypted
workspace integration exists. Selecting a vault folder for import creates a
plaintext copy, so do not do that for vault-only data.

Import omits `.git`, agent/plugin config directories, common credentials, `.env`
files, virtual environments and dependencies. It rejects symlinks and special
files and limits imports to 256 MiB/10,000 files. This is not a comprehensive
secret scanner: inspect your selected source for credentials in other filenames.
A new Git repository has no imported hooks or remotes. A local baseline commit
records the imported files so subsequent edits have a reviewable diff. Changes are not pushed to
GitHub automatically; review and transfer the patch through your existing workflow.

Read/glob/grep are allowed within the project; edits and shell commands ask.
External-directory tools, web fetching, web search and subagents are denied.
LSP/formatters are disabled to avoid automatic project executables/downloads.
Project OpenCode config is disabled. Provider keys and inherited OpenCode settings
are stripped from the subprocess environment; HOME itself is not changed.
These are native application permissions, **not an OS sandbox**. An approved shell
command runs with your Mac user's privileges and can access files or the network.
OpenCode's own first-run dependencies/web interface may also need internet access.
This release does not route approved shell networking through the VPN and does
not give the agent a web-search tool. Do not use shell commands as a replacement
for the VPN retrieval tools in Open WebUI.

## Native Open WebUI code execution

The pinned Open WebUI v0.11.1 already defaults `ENABLE_CODE_EXECUTION` and
`ENABLE_CODE_INTERPRETER` to true, with `pyodide` engines. The installer now makes
those values explicit. Earlier claims that this was definitely disabled were
incorrect. Availability in a particular chat still depends on its capability
settings and successful browser execution. Pyodide is browser-side Python, not
an unrestricted Mac terminal, and its resource/network boundary differs from the
Mac gateway. It does not automatically inherit the VPN or the vault file tools.

## Validation and acceptance

Authoring tests cover provider configuration, permissions, context limits,
credential-environment filtering, isolated copying, omitted configuration/hooks,
symlink/oversize failure and installer checksum rejection. Existing gateway tests
continue to cover native function-call translation and mode enforcement.
Upstream v1.18.34 source was checked for environment flags and configuration schema.
This is not an end-to-end OpenCode executable or native Mac acceptance result.

On the Mac, use a disposable folder with a tiny Python function and one failing
unittest. Confirm Plan does not edit, deny an edit/command and verify it does not
execute, then approve the correction/test. Verify only the copy changed. Check
model traffic uses the gateway, switching to Gaming stops the harness, and no
cloud model is available. Confirm session reopening and token/compaction handling.
In Open WebUI separately execute `print(2 + 2)` using its code interpreter and
verify the actual result returns before relying on it.

Sources:
- https://github.com/anomalyco/opencode/releases/tag/v1.18.34
- https://opencode.ai/docs/providers/
- https://opencode.ai/docs/web/
- https://opencode.ai/docs/permissions/
- https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/config.py
