# Bounded local tool loop

Implemented 2026-10-05. The gateway now owns a model/tool/model loop for ordinary text chat. No account authorisation, new service or third-party Python dependency is introduced. VPN web tools have since been connected to the same loop. Native model tool-selection reliability is not yet tested on the Mac.

## Available tools

| Tool | Arguments | Capability |
| --- | --- | --- |
| `calculate` | `expression`, a string up to 256 characters | Restricted numeric arithmetic with parentheses, +, -, *, /, //, %, ** |
| `get_current_time` | Optional `timezone`, an IANA name up to 64 characters | Current date/time; defaults to Europe/London |
| `search_web` | `query`, up to 500 characters | VPN search with up to three bounded source records |
| `read_page` | Public HTTP/HTTPS `url`, up to 4096 characters | VPN HTML/plain-text page evidence |

The calculator traverses an allowlisted Python syntax tree. It does not use `eval`, execute code, call functions, access attributes or resolve names. Numeric magnitude, exponent and expression-complexity limits apply. The clock uses local timezone data; it does not make a network request.

Try ordinary chat: “Use the calculator to work out (11434 + 12341) * 412” or “Use the current-time tool for Europe/London.” Tool execution depends on the model emitting a structured tool call. A plausible answer alone does not prove the model used a tool. Configured web tools are listed in WEB-ACCESS.md. Live acceptance for all three text presets remains pending.

## Operation

1. The existing engine selects/unloads models exactly as before and retains the serial execution slot for the entire interaction.
2. It sends ordinary text messages and the gateway-owned schemas to Ollama.
3. A normal answer ends the loop. Structured tool calls are checked and run sequentially.
4. Assistant calls and matching named `tool` results are appended to the in-memory conversation.
5. Ollama receives the updated conversation and can answer or request another tool round.

Open WebUI still sends ordinary chat. Client-supplied tools and tool-role messages are rejected, so a client cannot expand the registry. Tool definitions are supplied internally, not inherited from Open WebUI plugins. Schema definitions describe permissions; executable validation enforces them.

Intermediate tool calls/results are not stored in the WebUI chat database or streamed as progress cards. Only the final answer or visible failure appears. The loop preserves Ollama's optional `thinking` field for protocol continuity but does not display it or interpret it as tool instructions. Chat remains buffered with existing SSE keepalives.

## Limits

| Limit | Value |
| --- | --- |
| Tool-execution rounds | 6 |
| Total tool calls per message | 12, including failed calls |
| Calls executed at once | 1 |
| Worker execution deadline | 5 seconds for local tools; 140 seconds for web tools; capped by remaining loop time |
| Result per tool | 4 KiB |
| Total tool-result evidence | 16 KiB |
| Loop deadline | 900 seconds |
| Stored conversation budget | `num_ctx * 3` UTF-8 bytes, bounded to 4,000–100,000 bytes |

After six tool rounds the model has one further inference opportunity to answer; a seventh tool request is rejected before execution. An over-limit batch executes nothing. Malformed model responses fail visibly. Unknown tools and invalid schema arguments return structured errors without launching a worker. Runtime tool failures are returned to the model as errors, not successful evidence.

The byte budget bounds data storage, not exact model tokens. Long chats or accumulated evidence can fail the budget check earlier than the round/evidence limit. No history is silently trimmed. Start a shorter chat if necessary. This is not a guaranteed total RAM ceiling.

Each registered tool runs in a short-lived Python subprocess, with no shell and no inherited environment credentials. Web workers receive only their fixed loopback endpoint and retrieval key through private stdin; neither is injected into model messages. On timeout it is killed and reaped. A Python thread timeout is not used. This is process isolation for the two trusted tools, **not an OS filesystem/network sandbox**; future tools need their own permissions and isolation review. Do not extend the registry with arbitrary executable functions.

The loop applies remaining-time HTTP timeouts and checks its deadline between operations. Timing out a request does **not** forcibly cancel computation already running inside Ollama. Model cancellation and immediate Gaming transitions remain separate work. No fallback to another model or tool provider occurs.

## Scope and compatibility

- Enabled by default for ordinary text chat. To disable, stop Local AI, set `"tool_loop_enabled": false` in `~/LocalAI-Automated/control/config.json`, then restart. The flag must be a JSON boolean, and requests cannot override it.
- Explicit `/search` and `/read` retain their existing retrieval-then-answer path without exposing local tools to the retrieved page. Ordinary chat now advertises `search_web` and `read_page` when VPN web access is enabled; those tools use the same isolated endpoint.
- `/image` and `/video` retain their original explicit routing and memory handoff.
- No shell, arbitrary filesystem access, active GitHub/Dropbox account access or user-defined tool registration is available. A disabled GitHub adapter now supports tested read/proposal/approved-write paths; see [GitHub integration](GITHUB-INTEGRATION.md). The installer does not activate it.
- No account credentials are placed in schemas or tool messages by this implementation. Never paste credentials in ordinary chat.
- Custom text presets must support Ollama tools. Unsupported models may return a backend error. Disable the loop globally to retain the previous ordinary-chat path while investigating compatibility.
- Tool selection, final calculations and descriptions are still model-dependent. Executable arithmetic results are validated; whether the model uses or quotes them correctly requires evaluation.

## Modules and installation

`tool_registry.py` owns the fixed schemas and trusted implementations. `tool_executor.py` validates and manages worker processes. `tool_loop.py` owns conversation progression and bounds. `model_engine.py` calls the loop within the existing serial job. All three modules are in the installer's copy/fingerprint manifest.

Run the updated installer while Local AI is stopped. Existing data, presets, credentials and workflows are preserved. Downloads are reused; native generation checks may rerun because the gateway changed. Nothing needs adding to the VPN setup for these two entirely local tools.

## Verification

Tests cover multi-round/batch calls, preserved model settings/thinking, no-tool responses, unknown tools, strict arguments, prohibited arithmetic syntax, numeric limits, malformed/oversized results, process-start failures, actual calculator/clock workers, killing/reaping a real sleeping test process, deadline/call/round/evidence/context bounds and integration with the serial model engine. Installer and extracted-ZIP checks cover module inclusion and imports.

No real Ollama model was available here. Native acceptance still needs a calculator call, a clock call and a multi-round task on each text preset. Do not treat mock success as evidence that a 4B model will reliably select tools.

Primary protocol reference: [Ollama multi-turn tool calling](https://docs.ollama.com/capabilities/tool-calling).

## Natural-language web requests

With VPN web access configured, try “Search the web for Python's official tutorial and compare the first sources” or “Read https://www.python.org/ and summarise it.” The model can make successive web calls within the existing six-round/twelve-call limits. Search/page tools are omitted from schemas when web access is disabled; a forged web call still fails without starting a worker.

The web worker contacts only `http://127.0.0.1:8090`. It has no alternate provider or public downloader. Host-side redirects from that endpoint are refused; website redirects are handled and revalidated inside the VPN reader. Search/page errors return structured failures. A model may answer from its own knowledge after failure, so its claim of web-backed evidence must be checked against actual source links.

Web results are limited to three sources and approximately 1500 total evidence characters before the 4 KiB JSON cap. Metadata can force further truncation or a result-limit error; URLs are never cut to fit. This is short evidence, not full-document reading. Each successful source receives a unique number across all calls, and matching links are appended to the final answer. Duplicate URLs may appear with different numbers if retrieved again. Citation correctness remains model-dependent.

Tools run sequentially in the model engine. Web workers have a 140-second deadline and are killed/reaped on expiry. Killing the worker does not cancel a retrieval already executing inside the reader service; that service has its own bounded work and VPN firewall. Native VPN/drop/DNS tests remain pending.

Additional tests cover strict web schemas, credential separation, disabled/wrong endpoints, web deadlines, multi-call source numbering, failures without source links, redirect refusal and a real worker calling a fake loopback reader. They do not establish a live VPN or model's research reliability.
