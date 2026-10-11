> 2026-10-06 update: GitHub now has an official-MCP configuration helper, and
> the encrypted workspace exposes four mount-checked OpenAPI operations. See
> [ENCRYPTED-WORKSPACE.md](ENCRYPTED-WORKSPACE.md). No vault password is saved.
> Vault media and backup/restore helpers are implemented; native Mac/account/UI tests remain pending. Earlier text
> below describes the previous cleanup baseline where account setup was absent.

# Open WebUI owns tools; the gateway owns model memory

## Minimal global behaviour and tool awareness

The launcher provides one compact shared behaviour policy to Open WebUI and OpenCode.
Open WebUI uses `DEFAULT_INTERFACE_SETTINGS.system` so accounts that have not set
personal system instructions inherit it; existing personal and model-specific
system prompts take precedence. OpenCode prepends the same policy to active agent
prompts. Open WebUI and OpenCode continue to advertise their own allowed native
tool schemas. Simple questions need no tool call; additional capabilities are
investigated only when relevant. There is no capability-discovery agent, always-on
search, additional process or extra dependency. These defaults take effect when
services are relaunched from the updated installer; existing account overrides
are deliberately preserved. Tool permissions and approval rules are unchanged.


Updated 2026-10-05 UTC (2026-10-06 in London). Open WebUI remains pinned to 0.11.1.
This revision replaces the private agent loop with a tool-message compatibility
bridge. It does not claim native Mac or browser acceptance has passed.

## Removed and retained

Removed: `tool_loop.py`, `tool_registry.py`, `tool_executor.py`, `github_adapter.py`,
`github_mcp.py` and their retired tests. The calculator, current-time worker,
proposal digest store and custom commit approval controller are no longer active
code. Their previous implementation remains recoverable in Git history. No separate
approval website was built. `tool_loop_enabled` in old config is now ignored.

Retained: the serial model queue, text presets, keep_alive, confirmed Ollama unload,
ComfyUI start/stop, explicit media commands, private remote access, VPN containers,
reader and explicit web commands. GitHub/Dropbox account access is still absent.
An obsolete `github.enabled` setting is rejected rather than silently activated.

## New boundary and operation

1. Open WebUI sends its allowed function definitions and chat history to the gateway.
2. `tool_protocol.py` checks message/call structure and converts OpenAI call IDs and
   JSON arguments into Ollama's named-tool message format. Text content parts are
   supported; image/audio parts are rejected. Definitions are data, not executable code.
3. The model engine owns one serial inference operation, including preset selection,
   keep-alive and any model handoff. It does not execute or approve a tool.
4. Ollama's requested functions return as OpenAI-compatible assistant tool calls with
   IDs and JSON-string arguments. Both nonstream responses and buffered SSE preserve
   calls and `finish_reason: tool_calls`. Unadvertised/malformed calls fail visibly.
5. Open WebUI approves and executes the selected tools, persists the conversation,
   and submits the next inference request with matching tool results.
6. The gateway performs that next inference. It does not repeat an earlier slash
   command when the last message is a tool result.

This removes our custom approval URLs and result-delivery problem. Open WebUI
controls its own saved conversation. The gateway serializes individual inference
operations, not the entire multi-turn WebUI agent session. Another queued job can
run while a tool awaits approval. All heavy operations through the gateway still
share its model lifecycle queue; tools that directly start other backends bypass it.

Current bridge limits: at most 128 tool definitions (262,144 serialized bytes),
500 messages, 32 calls per assistant message and 65,536 bytes of arguments per
call. HTTP requests retain the 2 MB cap. `tool_choice: auto` and `none` are supported;
forced/required tool choice fails explicitly. This is not full OpenAI API parity.
Only one inference is sent per gateway request. Open WebUI owns loop limits and
tool execution timeouts. Cancellation and strict Gaming ceilings remain pending.

## Configuration supplied by the launcher

- `ENABLE_TOOL_PERMISSIONS=True` exposes Open WebUI's experimental approval control.
- `DEFAULT_MODEL_PARAMS` requests native function calling and `tool_approval_mode: ask`.
- Existing user/model/chat settings can override defaults. Verify saved chats actually
  pause before enabling account writes. This setting is not a backend authorization boundary.
- Native WebUI search/image generation stay disabled in this installer: public URL
  fetching and direct ComfyUI execution would not preserve our VPN/memory requirements.
- If VPN retrieval is configured, `TOOL_SERVER_CONNECTIONS` registers the authenticated
  server-side Local AI VPN retrieval OpenAPI connection. Enable it from Integrations
  for the chat or attach it to a model. It is not automatically attached to every chat.

The bridge serves `/tools/openapi.json`, `/tools/vpn_search_web` and
`/tools/vpn_read_page` on the existing loopback gateway, with bearer authentication.
It uses the existing fixed-loopback VPN client, no new public downloader and no
direct fallback. Web tool output is bounded evidence with URLs and truncation/error
labels; citation accuracy requires checking. The separate media listener does not
serve these endpoints. A phone calls Open WebUI through Tailscale; Open WebUI calls
the tool server on the Mac. No additional phone-facing approval port is introduced.

## On-demand capability discovery and registration check (October 2026)

Open WebUI also receives one short, configuration-derived list of registered
integration names in its inherited system prompt. This costs only a small fixed
number of tokens and does not inject any tool schemas, inspect services, expose
credentials or trigger background work. It reports registration, not chat access.

The installer registers a single **read-only LOCAL AI capabilities** OpenAPI
server with the existing authenticated gateway. It is *not* attached to every
chat. In Open WebUI, select **LOCAL AI capabilities** under Integrations only
when an unfamiliar task requires discovery; the model may then call
`discover_local_capabilities` with category `web`, `files`, `workspace`,
`browser`, `office`, `coding`, `media`, `desktop`, `delegation`,
`accounts` or `all`. Responses report non-secret configuration indicators
and required surfaces. They **never** claim that a tool is selected,
permitted, reachable, tested or ready. The endpoint cannot execute a tool,
read user files, access credentials, or activate an integration.

**Check Tool Availability.command** performs a separate, explicit, local,
read-only inspection. It checks that the gateway exposes the authenticated
discovery specification and that the tool servers generated by the installer
appear in the running Open WebUI configuration. It reports configured,
registered and missing server IDs, with no tokens or API keys printed or saved.
It does not run inference or modify service configuration. Exit code 1 means
the expected registration could not be verified, including when services are
not running. It cannot prove per-chat selection or successful tool calls.

OpenCode already checks connected MCP servers and effective Plan/Build
permissions on startup, including the Office tool and read/transfer/vision
tools. These checks remain unchanged and do not confer additional permissions.
When scoped automation is active, Open WebUI's ordinary tool integrations
remain suppressed by the existing safety policy.

**Limitation:** Open WebUI 0.11.1 requires external OpenAPI/MCP connections to
be selected for the chat. Registration by `TOOL_SERVER_CONNECTIONS` is not
automatic per-chat activation. The new index deliberately does not try to
circumvent this with prompt tricks or a privileged Python tool. For specific
automation or browsing tasks, select the relevant allowed integration in chat.
The global instructions remain short; simple questions have no discovery call.

## Built-in tools versus integrations

The current upstream catalogue includes these families. Feature flags, model
capabilities, user permissions and sometimes per-chat toggles control availability.
The catalogue can exceed the pinned release; it is not a list of features already
configured or tested by our installer.

| Family | Examples | Setup / project status |
| --- | --- | --- |
| Time | `get_current_timestamp`, `calculate_timestamp` | Native time tools; model category controls availability |
| Memory | Search/list/add/update/delete memories | Native storage; enable and validate if wanted |
| Notes | Search/read/create/edit notes | Native notes; feature/permission controls apply |
| Chat history | `search_chats`, `view_chat` | Searches the user's accessible saved chats |
| Knowledge and attachments | Semantic search, exact grep, paginated file reads | Uploads, parsing and embeddings need setup/testing; extra memory/storage |
| Web | `search_web`, `fetch_url` | Native implementation exists, but remains disabled here; use our VPN bridge |
| Images | `generate_image`, `edit_image` | Needs a backend; direct connection is not wired to our handoff policy |
| Code | `execute_code` | Execution engine required; not a general guarantee of secure arbitrary code |
| Tasks and questions | `create_tasks`, `update_task`, `ask_user` | Saved-chat task lists and interactive questions |
| Calendar, channels, automations | Search/manage events, channel search, scheduled runs | Optional native features; not external Google/Microsoft account access by default |
| Skills, delegation, notifications | `view_skill`, `delegate_task`, `timer`, `notify` | Optional configuration; not enabled/validated by this change |
| GitHub / Dropbox | Account tools via MCP/OpenAPI | External integrations, not built-in account connections; still unconfigured |
| Shell / filesystem | Open Terminal | Separate execution service; not installed by this revision |

## Approval limitations and acceptance

Open WebUI's approval mode is experimental and covers saved chats; temporary
chats, automations and channel replies do not provide the same approval boundary.
Full access is possible. Do not attach privileged write tools until denial,
approval, reload, cancellation and alternate chat contexts have been checked.
The native card displays arguments; it does not automatically promise a rich
before/after GitHub diff or file-conflict policy. GitHub's official write tool
uses a base file SHA, and account permissions must be constrained separately.

Authoring tests verify translation, ID/result matching, no hidden execution loop,
settings preservation, malformed-call denial, system-prompt continuity, real local
HTTP tool-call responses in both modes, VPN bridge validation and retained model
handoffs. They do not run the actual Open WebUI frontend, Ollama models or a VPN.

Before use on the Mac: verify built-in timestamp call and a saved-chat Allow/Deny
cycle; reload a paused chat; test multiple same-name calls and retained system
instructions; test the VPN connection from Safari and another device; confirm
actual VPN failure behavior. Evaluate a supported patched WebUI release before
account writes: upstream reported approval bugs in 0.11.1/0.11.2. Do not silently
upgrade an untested pinned dependency in this cleanup.

Primary sources checked:

- [Native tools and approval guide](https://docs.openwebui.com/features/extensibility/plugin/tools/)
- [0.11.1 approval release announcement](https://www.openwebui.com/blog/v0-11-1-the-model-learns-to-stop-and-ask)
- [Configuration](https://docs.openwebui.com/reference/env-configuration/)
- [Pinned 0.11.1 tool middleware](https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/utils/middleware.py)
- [Pinned 0.11.1 external-tool integration](https://github.com/open-webui/open-webui/blob/v0.11.1/backend/open_webui/utils/tools.py)
- [Reported approval regression](https://github.com/open-webui/open-webui/issues/29293)
- [Ollama chat API](https://docs.ollama.com/api/chat)
