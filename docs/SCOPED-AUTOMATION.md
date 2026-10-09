# Scoped desktop control and external reasoning

Implementation added on 9 October 2026. Both features are opt-in. Automated
security tests run with fake native/browser boundaries. Real macOS, pinned
Playwright image compatibility, DeepSeek selectors and coordinator end-to-end
acceptance remain pending until checked on the installed Mac.

## Implemented scope

| Capability | Implemented boundary |
|---|---|
| Desktop apps | Finder folder navigation in the copied project; activate Finder or Calculator |
| Session | Local approval; five minutes; 24 effectful calls; one controller process |
| Scripts | Fixed host-owned AppleScript only; values passed as arguments |
| External helper | Existing VPN Playwright MCP, one submission at a time |
| Outgoing text | Eight fixed public questions, selected by an enum; no free-text prompt |
| Approvals | A native Mac dialog for session access and every exact outgoing prompt |
| Stop | Local launcher or MCP tool; generation invalidates existing sessions even after rearm |
| Audit | Local action/status/time only; no paths, prompts, responses or tokens |
| Alternate tools | Independent OpenCode hook blocks shell, writes, other MCPs and raw browser controls |

No Accessibility or Full Disk Access is requested. The native subprocess denies
network access through the existing macOS sandbox facility. Its Finder calls are
fixed and scoped. The Apple Events permission macOS requests is still required.
A permission refusal fails without another implementation path.

This is a narrow first version, not general-purpose Mac control. It does not
implement arbitrary menus, Accessibility clicks, file moves/replacements,
application installation/removal, setting changes, message sending, screen
recording, closing apps or file deletion. Unsupported actions are refused rather
than offered as approval-required actions. Adding these requires individually
reviewed action adapters. An arbitrary AppleScript, keystroke or click endpoint
would undermine the agreed boundaries and is intentionally absent.

## Install and use

1. Update the installer source from this change and rerun the normal installer on
   the Mac. Existing disabled configurations retain their normal behaviour.
2. Stop Local AI before changing configuration. Run **Enable Desktop Control.command**.
3. Restart Local AI and **Start Work Agent.command**. Ask it to open the copied
   workspace in Finder or activate Calculator. `automation_begin` displays the
   actual copied workspace and requests a short local authorisation.
4. Use **Stop Automation.command** to stop a sequence. The marker stays latched.
   **Rearm Automation.command** requires local approval. Then begin a new session.
5. Close the work agent and stop Local AI before running
   **Disable Scoped Automation.command** to restore the ordinary tool profile.

The safety profile uses the existing coordinator but replaces specialist/media
hooks and disables other effectful tools while automation is enabled. Project
inspection remains available. Code editing, shell commands, Office writes,
local specialist delegation and ordinary browser interactions are unavailable
in this profile. Model-facing WebUI tool connections and its code interpreter
are also withheld. Use the ordinary profile for those workflows after disabling
scoped automation. This is a deliberate restriction of this first version, not a
claim that unrestricted tools can be made safe with a prompt instruction.

## External delegation setup

DeepSeek's official [Terms of Use](https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html)
were checked on 9 October 2026; the page says its last update was 27 March 2026.
Section 3.5(3) restricts automated copying/capture. The handover's generic statement
of permission does not establish that this particular submission-and-retrieval
workflow is covered. No external request was submitted during implementation.

Keep delegation disabled unless your provider permission specifically covers
both automated prompt submission and response retrieval. The local setup dialog
records your attestation of that scope and terms review. It does not verify the
permission with the provider. New terms require review and a code/config version
update; an old version value cannot enable the adapter.

1. Verify the existing VPN browser using **Check Browser.command**. No direct
   Mac browser or separate engine is started by delegation.
2. Manually establish your authorised login in that existing browser profile.
   This implementation does not automate credentials, login, challenges or
   rate-limit workarounds.
3. Observe the current fresh DeepSeek chat and record CSS selectors for:
   `input`, `submit`, `response`, `busy` and `challenge`. `response` must select
   final assistant answers only, excluding user prompts and reasoning panels.
   `busy` must remain visible throughout generation. `challenge` must identify
   blocking verification/rate-limit UI. Incorrect selectors can cause a blocked
   operation or an incomplete answer; these cannot be inferred reliably here.
4. Run **Enable External Delegation.command**, review the scope dialog and enter
   those locally verified selectors. Both VPN and browser must already be enabled.
5. Restart the runtime and work agent. Ask for one useful catalog explanation.
   It selects an enum and the controller constructs the exact public prompt.
   Review and approve the native dialog before it sends anything.

The catalog covers invariants, graph search, scheduling, idempotency, transactions,
probability, necessary/sufficient conditions and verification. Model-provided
prompt text, parameters, URLs, attachments, screenshots and approval flags are
rejected. Questions cannot be amended with private details. A task outside this
catalog stays local. This avoids claiming that a heuristic privacy filter can
reliably identify all private or unsafe content.

The adapter discovers the existing MCP's fixed-code tool name (`browser_run_code`
or the current `browser_run_code_unsafe`). Only host-owned static snippets reach
that tool; model code and filenames are never accepted. The current tool executes
in the browser server process, so raw access is denied by the independent guard.
See the [official tool contract](https://playwright.dev/mcp/tools/code-execution).

The adapter verifies a fresh chat, exact input text immediately before its one
submit click, expected origin and absence of the configured challenge. It uses
bounded response polling, a 90-second overall deadline and ten-second transport
timeouts. A single in-flight request can run to its transport timeout after stop;
no further step runs after invalidation. A submitted prompt cannot be recalled.
Failed or ambiguous submissions invalidate the session and are not retried.
The MCP session is closed after use; the browser login profile remains local.

Only the selected response text is returned to the coordinator, labelled
`untrusted_reference` and `verified: false`. Page snapshots, network logs and
console output are not returned by this adapter. The coordinator must check
claims locally. It cannot follow links or execute instructions in the answer
through an alternate effectful tool in the safety profile. Account/connection
metadata remains visible to the provider even for a generic question.

## Acceptance on the Mac

Run **Check Desktop Control.command** with the work agent closed. It performs
real approved Finder/Calculator calls, checks path restrictions, latches stop
and writes `automation-acceptance-report.json`. Rearm locally afterward.
**Check External Delegation.command** additionally submits one approved catalog
question through the configured browser and records retrieval status without
saving response content in its report. Do not run it without scoped provider
permission. These are native smoke checks, not coordinator end-to-end tests.

For end-to-end acceptance in the guarded work agent:

- Ask to open the copied workspace in Finder. Confirm the correct tool selection,
  the native approval, the target folder and an accurate final result.
- Deny a session approval and confirm no app interaction follows.
- Ask for Terminal, Keychain, an outside directory, a script, deletion or an upload.
  Confirm refusal and no alternate tool runs.
- During an approval dialog use Stop Automation.command. Confirm dialog process
  cancellation, no later action, and a new session only after local rearm.
- Stop then rearm between two tool calls. Confirm the old session stays invalid.
- Ask for a catalog explanation. Confirm the exact prompt dialog matches the
  generic text, denial makes no browser submission, approval submits once, and
  the response is treated as unverified reference material.
- Present private text, attachments or a custom prompt. Confirm no submission.
- Disconnect VPN, trigger a challenge or change a selector. Confirm failure with
  no network fallback or automatic resubmission.
- Inspect native effective permissions, tool-call history and the local audit.
  Mark each check passed/failed/pending from observations; do not infer success.

## Boundary limits

OpenCode hooks and native permissions are application-level enforcement. They
are not a complete OS sandbox for the coordinator. The desktop child has a real
network deny rule, but Finder itself is an Apple Events broker, not a
filesystem-sandboxed process. Fixed methods and canonical paths restrict what
this interface requests. Filesystem checks assume the trusted local user does
not concurrently replace approved folders. A hostile process running as the same
Mac user could edit policy/configuration, race paths or directly reach loopback
services; defending against that requires a separate OS identity or a stronger
broker and is beyond this lightweight implementation.

The privacy boundary protects submitted text by accepting fixed public strings.
Local context and external results still exist in local coordinator history.
The local user, provider account and browser session remain trusted setup
inputs. No secret access, privilege escalation, security changes, persistent
services, additional models or new browser engines were added.
