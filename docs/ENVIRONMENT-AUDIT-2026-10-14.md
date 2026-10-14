# Environment audit, 14 October 2026

The audit starts from published commit `5e94114` and preserves the existing
local-first tools, approvals, exclusive media handoffs and single installer.

| Issue | Correction |
| --- | --- |
| Idle-release test assumed at least two minutes of host uptime | Use an explicitly expired timestamp; fresh GitHub runners are valid |
| MiniCPM native acceptance expected removed specialist model IDs | Resolve the active role mapping, including shared-model installations |
| A mode change during a cold GGUF load could start stale inference | Recheck mode readiness after model startup and before completion |
| Captain provider and model backend could disagree | Reject mismatches and disabled-but-still-selected GGUF profiles |
| Backend tool-call IDs were replaced by generated IDs | Preserve validated native IDs and reject duplicate or malformed IDs |
| The GGUF path sent original images rather than normalized pixels | Translate validated messages while preserving tool/result pairing |
| Standalone multi-gigabyte downloads discarded interrupted progress | Resume partial downloads, checksum before installation, preserve invalid data |
| Interrupted initial git fetch left a directory that would not resume | Retry an incomplete pinned checkout without changing an existing valid HEAD |
| Acceptance observed only primary Ollama | Check shared Ollama and GGUF release as well as primary residency |
| A project report-directory symlink could redirect evidence writes | Reject non-directory or redirected report paths |
| Native step settings were instructions rather than a hard inference limit | Persist and enforce twelve inference attempts per worker at the host hook |

Additional regressions cover late worker completion after parent cancellation,
report preservation, fixed worker identities, and checksum failures.

## Verification

Authoring suites: 199 installer tests, 120 gateway tests, 84 JavaScript tests.
398 passed; five native/environment cases skipped. The deterministic installer
builder checks every shipped file and executable permission against source.

The previous GitHub revision passed native macOS PDF/OCR integration and built
the pinned MiniCPM llama-server. Its only failing test depended on fresh-runner
uptime, now corrected. This release adds a real pinned OpenCode protocol check
with synthetic loopback inference. It verifies overlapping native workers,
actual read/note tool execution, saved reports and retirement. It does not
test model judgment or GPU throughput.

## Remaining hardware acceptance

The owner's Mac is not available yet. Real MiniCPM weights, model/projector
compatibility, tool reliability, five-slot memory pressure and tokens per second
remain unmeasured. Microphone, VPN, Cryptomator mounts, desktop approvals,
sleep/wake and physical login/crash recovery still require their documented
checks on the installed Mac. No obsolete model weights are automatically deleted.
