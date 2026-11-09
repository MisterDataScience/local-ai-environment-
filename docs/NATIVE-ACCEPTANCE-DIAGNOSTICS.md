# Native Captain text diagnostics

Use `Diagnose Captain.command` from the extracted installer after a failed
Captain text check. It uses the existing installed Python environment and
verified model files under `~/LocalAI-Automated`. It does not download weights,
install packages, edit configuration, or change readiness receipts.

The probe requires Local AI to be stopped. It takes the installation lock and
refuses to use a busy gateway or native-model port. Thinking remains enabled.
It runs one native text generation with one decode slot through the production
request builder and response translator. The fixed-fixture request and native
response are captured during that single inference call.
This is a diagnostic for the text return; it does not qualify parallel workers
or the complete installation.

Run from Terminal:

```bash
/bin/bash ~/Downloads/LOCAL-AI-launcher-test/mac-local-ai-installer/Diagnose\ Captain.command
```

The printed JSON distinguishes a completed final answer, reasoning without a
final answer, output cutoff, request/startup failure, and abnormal shutdown.
Records are private files under `~/LocalAI-Automated/logs/native-acceptance`:

- `captain-text-probe-raw.json`: the fixed-fixture native request and response.
- `captain-text-probe.json`: the translated response and validation result.
- `captain-text-probe-summary.json`: the bounded summary printed in Terminal.
- `captain-probe-runtime.log`: model loading and shutdown diagnostics.

The raw and translated records can include reasoning from this fixed synthetic
test. Normal conversations are not captured by this diagnostic. Authentication
headers and the installed configuration are not saved into these reports.

The full installer also saves each text fixture response before validating its
final answer or model residency. Failures name the precise stage and diagnostic
file. An HTTP 200 response, reasoning text, or a partial answer does not establish
a successful final response. The existing output-cutoff and handoff requirements
remain enforced.

## Shutdown correction

The gateway and native model share an owned process group for recovery. A normal
stop now signals the gateway first and lets it stop its model once. If the
controller hangs, the private group still receives forced termination. Recorded
gateway recovery uses the same controller-first approach. Repeated signals to a
gateway already in cleanup are ignored. An abnormal native exit is reported.

This corrects the reproduced duplicate-interrupt path. It is not evidence that
the preceding text acceptance failure has been resolved. Read the saved text
response and exact failure reason before changing the model or return protocol.

## MiniCPM thinking protocol

When the selected model is from the pinned OpenBMB MiniCPM-V 4.7 repository and
its native server is running with thinking enabled, the shared request builder
merges this instruction into the leading system message:

> Always close your reasoning and then write the final answer as normal reply text.

Existing system instructions are retained. The reminder appears once, including
on streaming requests and worker turns that use the shared model. Caller history,
tool-call IDs, tool-result IDs and returned reasoning remain separate and intact.
Thinking flags, selected model files, the LoRA adapter and validators are unchanged.

The owner's controlled Mac probes used the existing selected weights, one decode
slot, seed 42 and temperature 0. The Python sentence failed to produce a final
answer without the reminder and passed with it in the recorded pair. The JSON
arithmetic fixture passed in both conditions. A corrected specialist fixture,
explicitly requiring an acceptance array, passed in both conditions too.

An earlier specialist fixture incorrectly described acceptance as one object
while its checker required an array. Its rejection is evidence of that diagnostic
ambiguity, not an established production handoff failure. The real handoff
instruction already includes the array shape, and its validator remains strict.

These are small, fixed-fixture observations. Native execution of this assembled
installer, full OpenCode handoffs, parallel workers and tool-evidence qualification
still require the normal installation acceptance on the target Mac. No success
receipt is derived from these diagnostic results.
