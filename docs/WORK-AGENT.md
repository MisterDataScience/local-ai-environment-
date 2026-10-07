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
Plan and Build use the Huihui Qwen3.5 4B coordinator. The native task tool calls
the 9B analyst or 12B coder through the same gateway. Available model entries
and context limits come from the current eligible presets.
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

The role contexts (8K coordinator, 32K analyst/document, 16K coder) and local
model tool reliability are constraints. Start
with small, well-scoped tasks. OpenCode's automatic compaction is enabled with a
2,048-token buffer; it does not make a small context unlimited or guarantee that
all tool schemas fit. Advertised output is 4,096 in Normal or 8,192 in Max,
bounded further to half a custom smaller context. Restart after a mode change
to refresh these limits. Real local-model task performance remains unverified.


## Bounded model team

The narrow `opencode-team.mjs` policy plugin uses native OpenCode task sessions;
it does not run another inference loop. Plan/Build decide when analysis or code
help is worthwhile. Routine work stays with the coordinator. `/code TEXT` and
`/analyse TEXT` directly select a specialist without a coordinator pass;
`/document TEXT` uses the larger 32K profile of the same 4B model. The coder can inspect project files, implement changes and run tests, using native
approval prompts for edits and commands. This applies to Build delegations and
direct `/code` requests. A coder called by Plan is read-only. The analyst and
document agents still return text without tool access.

Each explicit user turn gets at most two specialist attempts, including one
retry for a concrete failure. A second call to the same role must state that
failure. Mixed tasks can use each specialist once. Attempts are reserved before
execution and remain consumed after failures, interruption, reconnection or
restart. Native compaction continuations and overflow replays do not reset them.
Only native user-message IDs registered by the chat hook grant a budget; neither
model arguments nor arbitrary labels do. Existing pre-upgrade conversations need
a fresh user message before delegation.

The task prompt is a JSON object with string fields `objective`, `constraints`,
`evidence`, `completed`, `remaining`, and `result`, plus `retry_failure` when needed.
Input is limited to 12,000 characters. Evidence must contain relevant excerpts;
paths are references, not implicit access grants. The plugin escapes native
`@file` expansion and refuses non-text child attachments. The coder reads files itself rather than relying only on copied excerpts. It
reports changed files, actual test commands/results and remaining issues, keeping
full changes in the project copy. Other specialists report results, references,
assumptions, unresolved issues and validation actually run.
Native child responses remain in their sessions; parent excerpts above 12,000
characters are visibly clipped. Context overflow still fails explicitly.

Delegations run in the foreground, one at a time per parent session. No task
resumption, nested delegation or background task option is enabled. The gateway
serializes all inference and releases outgoing weights or context profiles before
loading the next. A failed unload prevents the next inference. Mode changes and
gateway restarts invalidate the work-agent binding and require relaunching it.

The private `work-agent/state/team-budget.json` ledger holds hashed turn keys,
call IDs, roles and status, without prompts/results or credentials. Its bounded
10,000-turn capacity fails closed instead of deleting records and resetting old
budgets. All plugin instances in the process share serialized accounting. Keep
this file when reopening sessions. Archive the whole work-agent state together
when retiring old sessions; deleting only the ledger is not a supported reset.

The base configuration denies task. Successful plugin initialization enables
only analyst/coder on the coordinator. Startup reads OpenCode's effective agents
and refuses to continue if these permissions did not load. Set
`model_team.enabled` to `false` in `control/config.json` with services stopped to
disable delegation. This leaves installed presets selectable and restores the
previous single-agent configuration. The installer preserves this setting.

## Coder execution limits and acceptance

The coder is limited to 12 model steps and 24 native tool attempts per delegated
task or direct user turn. Denied/error attempts count in native session history;
reconnecting does not reset them. Delegation still consumes one of the parent's
two specialist attempts. Failed work can use the remaining retry when its concrete
failure is supplied. No extra model is loaded for approvals or monitoring.

The policy verifies the coder's actual native assistant identity and its active,
reserved parent task before child tools can run. Plan restrictions are enforced
explicitly because upstream OpenCode does not inherit the parent agent's own
permissions into the child. Build and direct-coder edits/commands still pass
through native OpenCode approval prompts. The plugin never auto-approves them.
A changed resource mode or gateway instance blocks further coder tools.

Startup checks the effective coder permissions, including edit/bash set to ask,
`.env` read denial and task/network-tool denial. Automated Mac acceptance requires
the coder to inspect a disposable project file using its actual native read tool.
It does not silently grant edit/shell approval during headless installation.

For native execution acceptance, use a disposable project copy with a small bug
and a failing test. In Plan, verify coder file inspection works and edits/commands
are blocked. In Build or `/code`, deny an edit and confirm the file is unchanged;
then approve the edit and the test command and inspect the resulting diff and
actual test output. Confirm only the project copy changed. These native approval,
file-edit and command-execution checks remain pending on the Mac.

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
External-directory tools, web fetching and web search are denied. Only the
allowlisted analyst/coder subagents can be called by Plan or Build. The analyst/document agents have no tools. The coder can use read/glob/grep,
plus edit/write/apply_patch and bash with native approval. It cannot delegate,
use account/network tools, or expand its directory permissions. General and
Explore agents are disabled.
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


Context budgeting now advertises input as context minus the mode's output ceiling. Native compaction then subtracts its reserve (up to 2,048 tokens, reduced for small contexts), leaving room for instructions and tool work. Gateway requests disable Ollama truncation and context shifting; oversized input returns context_length_exceeded instead of silently losing history. See [context management](CONTEXT-MANAGEMENT.md) for mode budgets and native acceptance.
