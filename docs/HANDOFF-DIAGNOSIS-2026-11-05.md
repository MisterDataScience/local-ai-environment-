# Native handoff diagnosis, 5 November 2026

## Conclusion

The current installation failure is in the specialist return protocol. The evidence does not show a compilation failure or failure to start inference. Earlier defects in the installer and instruction flow were real, but correcting each defect has not established a reliable complete workflow.

The 16:44 to 16:46 run stops at the **analyst**. It does not reach the inspection-only Plan coder introduced in the latest candidate. That coder change therefore remains unverified on the owner's Mac.

The exact cause of this latest analyst rejection is still unknown. The supplied terminal output identifies a saved report but does not contain its issues, raw response or native tool records. We must read that report before attributing this rejection to formatting, false execution claims, a cutoff, or a different contract problem.

Calling the earlier behaviour intentional lying would go beyond the evidence. The demonstrated behaviour was an unsupported claim of successful command execution after the command was rejected. The host correctly withheld acceptance for that structured claim.

## Evidence and chronology

Times below are from the supplied Mac output on 5 November 2026. The UK is on GMT.

| Run or report time | What the evidence establishes | What it does not establish |
| --- | --- | --- |
| 15:47 | A native task completed, but its return failed contract validation. | The complete delegation workflow was not accepted. |
| Earlier analyst report | Correct arithmetic returned as prose instead of required JSON. | This was not an arithmetic failure. |
| 16:09:32 | Analyst report was `ready_for_review`, with no issues and structurally valid JSON. | One successful sample does not establish repeatability. Analysis was labelled `specialist_claim`. |
| 16:10:05 | Coder mixed prose with a fenced JSON object and supplied `read` in place of the native call ID. | Read-only file inspection was not yet accepted by the contract. |
| 16:25:23 | Coder returned valid JSON, cited the genuine successful read, attempted a shell command that ended in `error`, and nevertheless reported the command as `passed`. | The command did not have successful execution evidence. No successful shell execution is shown. |
| 16:44:25 to 16:46:01 | Updated installer ran 144 backend tests with one skip, finished text checks, started specialist acceptance, and stopped on the analyst's rejected return. | The latest analyst's rejection reason is not included. No Plan coder or Captain dispatch acceptance is shown in this run. |

The latest report filename in the supplied log is `dd700f8fe7a275decf616eb6316b8586fd39b6946e8ce647873efe973b142849.json` under `work-agent/acceptance/.local-ai-handoffs`.

## Findings from source and reproducible checks

### 1. Strict return protocol, unconstrained text generation

`opencode-team.mjs` inserts `RESULT_INSTRUCTION` into the child's JSON brief as a string-valued `return_format`. `handoff-contract.mjs` later calls `JSON.parse` on the full assistant text.

The native task path inspected in OpenCode 1.18.34 calls the child prompt API without a structured-output format. The protocol is therefore a model instruction followed by strict post-generation validation. It is not a schema-enforced generation path.

This explains a class of repeated failures: valid JSON, a fenced object, and a prose answer may convey the same arithmetic while only one meets the transport contract. It does not identify the exact latest failure without its report.

The analyst profile in `work_agent.py` also has no explicit sampling configuration. The precise sampler used in the latest Mac request is not present in the evidence. Lower temperature alone would not establish schema compliance or semantic correctness.

### 2. Structured-output support is incomplete across the bridge

Two direct checks were run against the real gateway modules, with only the backend transport replaced by a local fixture:

| Probe | Observed result |
| --- | --- |
| Send `response_format` containing a JSON schema into `SharedLlama.chat` | The backend payload omits `response_format`. Ordinary prose is returned unchanged. |
| Submit `tool_choice: required` through `tools_for_ollama` | Rejected: this bridge currently permits only `auto` or `none`. |

OpenCode 1.18.34 implements its native structured-output option using a `StructuredOutput` tool and `toolChoice: required`. Switching that option on would encounter the bridge restriction. The existing task invocation also does not propagate such a format to the child.

Consequently, adding another sentence about JSON, or adding `response_format` at a caller without verifying the outbound backend payload, is not a sufficient integration fix.

### 3. Analyst and coder are profiles over the same core model

`captain_setup.install_minicpm` selects the pinned MiniCPM model and adapter, sets `single_model=True`, and removes unused stock analyst/coder entries from the download plan. `model_team.team_roles` then resolves coordinator, analyst and coder to `local-ai-captain`. A stock document profile may remain separate.

A direct role-resolution probe reproduced:

```json
{
  "coordinator": "local-ai-captain",
  "document": "local-ai-team-document",
  "analyst": "local-ai-captain",
  "coder": "local-ai-captain"
}
```

This is the current core setup's intended behaviour. A role name does not imply a separate reasoning or coding model. A correct agent route is not evidence of that model's reliability under the role's instructions.

There is no evidence yet that the quantisation or adapter caused these failures. Changing either before a controlled comparison would introduce another variable.

### 4. The validator checks particular evidence claims, not universal truth

The production `assessResult` function was replayed with controlled inputs:

| Input | Status |
| --- | --- |
| Valid analyst JSON with the correct arithmetic | `ready_for_review` |
| The same JSON surrounded by prose and a code fence | `needs_attention` |
| Valid inspection JSON citing an actual completed read | `ready_for_review` |
| A structured `passed` test claim without a matching successful command | `needs_attention` |
| An unsupported claim of successful shell execution only in the evidence prose, with an empty test list | `ready_for_review` |
| Structurally valid analyst JSON asserting `17 * 19 = 999` | `ready_for_review` |

The last two outcomes show the limit of this check. Its own caveat correctly says that recorded tool execution does not prove semantic correctness. `ready_for_review` must retain that meaning.

The earlier rejection of the fabricated test entry was useful. It was not proof that all possible false execution claims or incorrect answers are detected.

### 5. The Plan tool correction addresses a real issue, but not this analyst failure

The former coder profile advertised approval-controlled shell and editing tools. A later policy hook rejected their use under a Plan parent. This let the model choose a tool it could see but could not use in that context.

The new hidden `coder-plan` profile denies those tools in its native permission set. The host selects it from the actual parent agent, and retains the execution-time restrictions. OpenCode's request-preparation source filters denied tools before inference.

That is a reasonable correction to the visible-tool mismatch. It cannot cure a tool-free analyst's return problem. The latest run stops before exercising the new coder path.

### 6. Automated test passes were overstated as evidence of readiness

The configuration, hook and validator tests are useful implementation checks. The acceptance test in `test_model_team.py` mocks the native process and HTTP responses. Its successful fixture supplies `localTeamReview: ready_for_review` rather than obtaining it from a real model run.

The pinned native protocol script uses scripted inference responses. It can establish compatibility between actual OpenCode, permissions, tool schemas and plugins when run successfully. It cannot establish that the selected neural model repeatedly follows the contract.

The owner's 144 passing tests exercise backend logic and protocol fixtures. The subsequent live handoff test is a separate level of evidence. Passing the former does not imply the latter will pass.

### 7. The installer makes diagnosis and iteration more expensive than necessary

`verify_native_handoffs` runs analyst before coder and throws on the first failed role. The caller extends its overall acceptance list only after the function returns. Thus an earlier role's success can disappear from the top-level saved report when a later role fails, even though its detailed handoff report survives.

The core success fingerprint is saved after generation acceptance succeeds. A failed run consequently repeats earlier preparation and checks on resume. That preserves the final gate, but makes a one-role investigation look like another full installation.

Per-role progress should be saved as each check completes, with a distinct failed check recording the report path and issue list. A scoped acceptance command should rerun only the selected checks against running verified services and must not mark the full system ready.

## Corrective approach

1. **Read the exact latest report and preserve the failing case.** Capture the final text, issues, contract, tool records, final-message finish/error metadata, actual agent/model route and relevant sampling settings. Keep any prompt capture limited to explicit acceptance fixtures, rather than enabling blanket logging of private chats.
2. **Test host plumbing with controlled replies.** Use the real pinned OpenCode binary, the real plugins and a scripted local inference endpoint. Verify raw outbound tool schemas, profile selection, receipt IDs, success/failure reporting, retries and preservation of negative evidence.
3. **Implement one complete final-return protocol.** Either carry a validated schema all the way through the gateway to the selected backend's final-response generation, or implement a host-owned return tool with validated arguments and the necessary supported tool-choice handling. Coder inspection rounds and final-result generation need distinct handling; blindly forcing a final JSON schema on every tool-use round is not sufficient.
4. **Keep execution receipts under host control.** Store actual command IDs, arguments, statuses and exits from native records. Retain model-authored evidence and claims separately, with comparisons that reject unsupported claims. Do not silently upgrade the result of a rejected command to a pass, strip contrary prose to get a green result, or remove acceptance requirements.
5. **Measure the actual model after plumbing is proven.** Use a fixed suite covering format compliance, correct arithmetic, successful reads, rejected commands, blocked work and honest non-execution reporting. Record all trials, the exact model/adapter/quantisation and sampler settings. A lucky successful rerun must not replace a reliability measurement. Synthetic protocol tests do not count as model trials.
6. **Improve scoped diagnostics before requesting further full reruns.** Provide one bounded result report that distinguishes software installation, inference availability, native protocol compatibility and model-workflow qualification. Keep overall readiness failed until all required gates pass.

The Plan coder profile should be retained while its native filtering is verified. The evidence checks should also be retained. The next release should be based on a complete protocol test and the actual model's measured behaviour, not another unmeasured prompt patch.

## Investigation limits

- The latest saved analyst report was not included in the supplied attachment. Its precise rejection reason remains open.
- The owner's native Mac, installed private configuration and model weights are not accessible from this environment.
- The official OpenCode 1.18.34 Linux baseline archive was downloaded and matched SHA-256 `24b0d458d21ef548b2752166303defcf7f4945b049fb4876ab78dfaf86d81b27`. Its binary aborts with exit 134 in this environment before serving. The attempted native scripted replay therefore did not run. This is an investigation-environment limitation, not evidence of a Mac defect.
- Source inspection, direct bridge probes, role-resolution and production-validator replays did run. None of these substitutes for live acceptance on the target model and Mac.
- No replacement installer or new GitHub publication was made as part of this diagnosis.

## Source map

Repository paths refer to the local candidate under investigation:

| Source | Relevant behaviour |
| --- | --- |
| `installer/captain_setup.py`, `install_minicpm` | Pinned model selection and shared-model configuration |
| `installer/payload/model_team.py`, `team_roles` | Effective role-to-model mapping |
| `installer/work_agent.py`, `configuration` | Specialist prompts and native tool permissions |
| `installer/opencode-team.mjs`, task before/after hooks | Contract insertion, profile selection and result validation |
| `installer/handoff-contract.mjs`, `assessResult` | JSON parsing and evidence checks |
| `installer/payload/shared_llama.py`, `SharedLlama.chat` | Backend payload construction |
| `installer/payload/tool_protocol.py`, `tools_for_ollama` | Tool-choice restrictions |
| `installer/team_setup.py`, `verify_native_handoffs` | Live specialist acceptance and stopping conditions |
| `installer/installer.py`, `verify_generation` | Gate sequencing and acceptance persistence |
| `installer/tests/test_model_team.py` | Mocked native acceptance fixtures |
| `scripts/check_native_captain.py` | Native OpenCode checks using scripted inference |

Pinned upstream sources inspected:

- [OpenCode task invocation](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/tool/task.ts)
- [OpenCode prompt loop and structured output](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/session/prompt.ts)
- [OpenCode request preparation and tool filtering](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/session/llm/request.ts)
- [OpenCode subagent permission inheritance](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/agent/subagent-permissions.ts)
