# Integrated release validation

**Release:** `2026-10-13-captain-workers-1`
**Date:** 13 October 2026
**Canonical source:** `main`
**Installer:** `downloads/Mac-Local-AI-Automated-Installer.zip`

## Captain implementation

The release includes native worker cohorts, a task board and peer messages,
shared text admission, exclusive model barriers and MiniCPM desktop setup.
Authoring tests ran 195 installer cases (5 native/environment cases skipped),
116 gateway cases and 81 JavaScript cases: 387 passed, 5 skipped, no failures.
They use simulated model responses and temporary local HTTP services. These
results verify host behaviour; they do not measure local-model quality or GPU speed.

The native desktop runtime build has a dedicated CI job at its pinned source
revision; its result is pending publication. `Check Captain.command` runs real OpenCode/model dispatch, evidence
reading, reports and retirement on the new Mac. Full installation invokes it
alongside existing native acceptance. Owner-Mac performance, real MiniCPM tool
reliability and five-slot memory pressure remain pending.

Read [Captain and workers](CAPTAIN-AND-WORKERS.md) for the active architecture.
The feature validation record below describes earlier integrated capabilities.

## Included changes

The vision/PDF/operations/file-workflow update and scoped desktop/external-helper
update are integrated into the same source and installer. Normal Work Agent
startup verifies the PDF, file, vision and Office connections. Scoped automation
startup verifies its restricted controller and does not activate or publish the
normal effectful workflow connections.

Audit corrections:

- Scheduled requests set `inference_only`; the gateway rejects all six command
  routes and supplied function tools before model/backend admission.
- Scheduled length cutoffs are retained as partial files with `incomplete`
  status and are not silently retried in the same schedule slot.
- Non-object JSON returns a structured 400 response and does not admit work.
  Audio request shape is checked as well. Gateway socket I/O has a finite timeout.
- Browser explicit interactive approval rules now match their regression tests.
- The installer is built reproducibly and checked against every source and guide
  file, including executable permissions. CI rejects a stale ZIP.

## Checks executed on the authoring host

| Check | Result |
| --- | --- |
| Installer Python | 162 discovered: 158 passed, four Apple-only tests skipped |
| Gateway/payload Python | 104 passed |
| JavaScript policy/workflow | 74 passed |
| Pinned WebUI 0.11.1 source compatibility | Passed as part of the installer suite |
| Release builder regression | Passed; detects changed source, missing package files and lost executable permission |
| Archive integrity and complete source comparison | Passed |
| Reproducible archive bytes | Passed on the authoring host |
| Python compilation and installer shell syntax | Passed |

The combined launcher regression exercises both normal and scoped profiles.
Scheduled regressions exercise all command prefixes, including uppercase and
whitespace forms, through the real gateway admission function. HTTP shape
regressions use a real loopback server. Other inference/provider responses are
synthetic where required by the existing suites. No external prompt or native
desktop action was submitted during this release's authoring verification.

## Optional finite autonomous jobs

The new unattended document-batch worker is separate from the interactive
OpenCode delegation policy and existing text-only recurring scheduler. It
checkpoints an explicitly authorised finite inventory, makes tool-free local
model calls and creates only job-owned Markdown files. Host tests cover its
state machine and recovery logic. Native launchd behavior, interruption timing,
model output quality and memory pressure remain unverified on the owner's Mac.
See [AUTONOMOUS-JOBS.md](AUTONOMOUS-JOBS.md).

## Native checks still required

The optional conversation browser UI test was not run successfully because this
host lacks Chromium; a browser installation attempt failed in Playwright's
directory-lock handling. Four Apple PDFKit/Vision tests are skipped on Linux;
the macOS CI job runs those against the integrated revision.

The owner's installed Mac has not been exercised here. GPU inference,
32 GB memory pressure, microphone/AEC, desktop Apple Events and approval denial,
emergency-stop behavior during native actions, actual provider selectors/MCP,
VPN exit and tunnel drop, physical login/crash/sleep/wake and the browser-to-
Office-to-vault journey require observed acceptance there. Cryptomator create-only
file publication must be checked on its actual mount backend.

Use `Check Required Capabilities.command`, `Check Office.command`,
`Check Browser.command`, `Check Conversation.command`,
`Check Desktop Control.command` and, only within authorised provider scope,
`Check External Delegation.command`. Their guides specify the live checks.
Installation readiness does not constitute owner-Mac acceptance.

## Release maintenance

After changing installer sources or feature guides:

```bash
python3 scripts/build_installer.py
python3 scripts/build_installer.py --check
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

Commit the source and rebuilt ZIP together. `RELEASE.json` inside the package
binds its contents by SHA-256; it is an integrity/provenance record, not a digital
signature or a claim of native acceptance.
