# PR 12 recovery validation, 16 October 2026

## Decision

Keep PR #12 in draft. Do not merge or publish a new installer yet. All feasible
local regressions pass, but the final native OpenCode check could not execute
on this host, and final native macOS checks remain outstanding. The published
ZIP on main is unchanged. This work preserves the single Captain installer.

Reviewed starting head: `8f5575dd5700feeb65076784868996474a403e8d`.
Main at review: `1448677eb7b3442efd227b3e59e6446c8766f354`.

## Confirmed CI blocker

The owner supplied the GitHub annotation: the job was not started because
recent account payments failed or the spending limit needed to be increased.
The billing screenshot showed $12 of included Actions usage/credits. It did
not establish an outstanding balance. The unavailable hosted allowance is the
working blocker; those zero-step failures provide no code-test result.
No workflow was dispatched, rerun or intentionally triggered in this recovery.

The workflow is now manual-only. Native macOS jobs require explicit opt-in,
and publication still requires all three gates to succeed on main. The one
recovery commit uses `[skip ci]` to prevent the preceding PR workflow from
starting during the transition. Existing failed checks were not marked passed.

## Fixes after review

### Installation reproducibility

- Added a transitive, artifact-hashed 85-package ComfyUI lock for CPython 3.12,
  macOS 15+ ARM64, including the pinned Torch trio. Installation uses
  `--require-hashes --only-binary :all:`. A changed lock hash invalidates the
  dependency checkpoint. Other environments are not all transitively locked.
- Verify existing ComfyUI upstream files against the pinned source archive
  instead of treating any existing main.py as proof of the intended revision.
  Repair missing files after interrupted extraction without creating nested
  source directories or replacing models, outputs, extra workflows or nodes.
  Modified upstream files and source symlinks stop safely without being blessed.
- Retry rejected download ranges once with a full HTTPS transfer, then retain
  mandatory checksum verification. General network failures keep their partial
  data for a later retry.
- Reject symlinked uv bootstrap targets before attempting even `uv --version`.
- Independently matched the uv ARM and OpenCode Mac/Linux release digests to
  their upstream GitHub release metadata. The ComfyUI source requirements were
  retrieved at the pinned commit. The Docker DMG and ComfyUI archive were not
  independently downloaded again on this host; native signature/MPS checks
  remain pending. No security checks were weakened.

### Remote Captain

- The guided remote readiness check now requires unauthenticated rejection and
  authenticated HTML at the Captain root, in addition to authenticated native
  Plan/Build agents. An API-only endpoint cannot satisfy that check.
- Keep credential-bearing requests on the exact configured private origin and
  refuse redirects. Explicitly retain off-device and browser-approval status
  as pending.
- Reopen Tailscale when stopped/unavailable before reconciling routes. Preserve
  hostname/conflict/Funnel checks and owner-account sign-in boundaries.
- Roll back an attempted missing Serve route even when its CLI invocation times
  out after potentially applying it. Existing routes are not reset.

### Headless reliability

- Reopen Docker when VPN health is lost, then recreate the managed VPN stack.
  A healthy stack does not repeatedly relaunch Docker. Failure has no ordinary
  network browser fallback.
- Include the gateway in repeated core health checks so a persistently hung
  gateway can fail the supervisor and reach the existing launchd restart path.
- Clean up a failed Captain readiness attempt before recording/retrying it.
- Reacquire the process-bound caffeinate assertion if its process exits.
- Preserve user LaunchAgent startup after login, owned-process checks,
  FileVault/owner-unlock requirements and deliberate sleep behavior.

## Checks actually run

Local host: Linux, CPython 3.12.14. Test-only dependencies were installed in
scratch, including the pinned Open WebUI wheel; no personal credentials or
model weights were used. Temporary directories were explicitly kept writable.

| Check | Outcome |
| --- | --- |
| Installer Python suite | 254 discovered: 250 passed, four native Apple PDF tests skipped |
| Gateway/payload Python suite | 126 passed |
| JavaScript policy/workflow suite, excluding browser test | 84 passed |
| Installer build regression | One passed |
| Existing manual-setup gateway regressions | 10 passed |
| Python compileall, installer shell syntax, git diff whitespace | Passed |
| Workflow YAML and manual/native/publication gates | Parsed and assertions passed |
| Deterministic installer candidate build and source/permission verification | Passed locally; candidate not published |
| Pinned uv 0.12.20 macOS 15 ARM64 dependency resolution | 85 packages resolved with wheel-only policy and release cutoff |
| Hash-enforcing installation dry run of checked-in ComfyUI lock | Passed for all 85 packages; did not install or execute Mac wheels |
| Native OpenCode 1.18.34, standard and baseline npm builds | Both aborted with SIGABRT before startup; native protocol test could not run |

The standard OpenCode npm archive was independently checked against its
registry SHA-512 integrity metadata. npm verified its baseline archive during
packing. Neither binary's abort proves a Captain code defect or native
compatibility. No cause for that host-level execution failure was established.

The previous successful CI at `008bb9af` remains useful historical evidence,
but is not a pass for this final patch. These tests also do not establish
CPython 3.11-specific or native Metal/PDFKit behavior.

## Remaining release and physical gates

1. Execute the final pinned native OpenCode web test, including served HTML,
   authenticated API/SSE and real native delegation, on a supported host.
   Real approval/denial prompts and UI interaction remain unverified.
2. Validate fresh native Mac install and interrupted/repeat install with the
   new hash lock, Docker signature and licence path, uv archive layout,
   ComfyUI imports/MPS and owner permissions. A cross-platform dry run cannot
   replace this.
3. Observe Windows and iPad sessions through actual Tailscale Serve: login,
   events, delegation, approve/deny, reconnection and private-route isolation.
4. Observe real login/reboot, Docker/Tailscale crash recovery, gateway/Captain
   failures, idle overnight, deliberate sleep, FileVault and vault unlock.
5. Restore native release validation without raising the owner's spending
   limit implicitly. Only publish once all required gates have passed on the
   final source. Do not replace the published ZIP using this local candidate.

Full release-wide Python/container locking remains incomplete. Docker image
digests are recorded at first install, but some initial image tags can still
resolve differently across fresh installations. See DEPENDENCY-LOCKS.md for
the exact implemented scope and regeneration process.
