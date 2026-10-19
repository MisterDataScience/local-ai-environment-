# Integrated release validation

## Layered resident-memory preview, 19 October 2026

Release `2026-10-19-layered-memory-preview` replaces automatic recent-memory
selection with separately owner-approved starting maps. Identity and profile
instructions remain first; curated fast-access memories, deeper-memory glossary
entries and preferred Library/Archive sources guide selective reading. Named
`map:` references resolve through the existing read tool with the current resident
identity, request scopes, approved target revision and live source checks.
The additive v1-to-v2 migration preserves approved data and rolls back on failure.
The dashboard provides entry selectors, intended-use fields, scoped search topics,
exact preview/final approval, clearing and revision inspection. It starts no inference.

Focused checks for this update: eight new starting-map Python, 15 Commons core,
18 Village/archive/facilities, nine Captain setup, 26 installer, six Commons
HTTP/transport, 47 Captain/OpenCode JavaScript and one release-builder regression:
130 passing checks. The JavaScript cases include the real Python/SQLite bridge
supplying a curated native worker packet and following a named workflow and
own-memory topic. Tests cover no recency fallback, own-memory isolation, private
scopes, stale target/map digests, explicit publication versus map approval,
withdrawal/correction/deletion, area-specific retrieval, navigation bounds, map
clearing, migration preservation, rollback and future-version write refusal.

Python and JavaScript syntax, source/installer contents and permissions, and an
identical deterministic second ZIP build are checked for the published artifact.
The existing gateway import dependency is supplied from the authoring runtime's
pip-vendored requests; no package download is needed. Native Mac browser layout,
real model navigation quality, installation and performance remain unverified.
Village encrypted backup/restore and complete source deletion are still pending;
removing a map entry does not erase map history or previously supplied context.
See [Resident memory and starting maps](RESIDENT-MEMORY.md) for usage and limits.
No Actions were dispatched or rerun. The publishing commit uses `[skip ci]`.
The earlier preview evidence below is historical.

## Village Commons preview, 19 October 2026

Development release `2026-10-19-village-commons-preview` extends the same draft
Village branch and canonical installer. It does not deploy to the owner's Mac.
See [the practical Commons guide](VILLAGE-COMMONS.md).

Commons uses the existing shared local inference queue: four active residents
by default with one extra foreground slot required, fair rotation, one coder at
a time, real clock/turn/conservative-token limits, foreground pause and explicit
resume. There is no automatic opening, background review or outsourcing. The
owner page provides formats, selective rooms, private drafts/reveal, exact context
inspection and separate final approvals for documents, Archive snapshots,
individual memories and persistent pointers. Expiring quarantine is excluded
from regular Village retrieval. Approved memories retain evidence and revisions;
source withdrawal, current grants and resident identity are rechecked.

Focused authoring validation:

- Commons core: 14 Python checks with real SQLite and synthetic responses.
  Covers four concurrent requests and rotation, independent openings, clocks,
  budgets, scopes, private research denial, draft/reveal/room isolation, exact
  approvals, source dependency withdrawal, forgetting, correction/deletion and
  approval replay. No private user corpus was used.
- Commons gateway/transport: six checks, including four real Engine queue
  admissions paused by a foreground request, authenticated owner HTTP and media
  isolation, forbidden remote/tool endpoints, queue cancellation and closing an
  actual stalled local inference HTTP socket.
- Existing affected suites: 11 shared inference/backend, four native Captain
  capacity, 25 gateway, 18 Village/archive/facilities, nine Captain setup and
  26 installer Python checks. Captain/OpenCode JavaScript: 46 checks.
- Builder regression: one check for deterministic output, stale source refusal,
  missing files and incorrect permissions. Full package contents/permissions/
  manifest verification and identical second build are required before publishing.
- Python compilation, Captain JavaScript syntax and extracted dashboard script
  syntax checked. The authoring runtime's pip-vendored requests supplied the
  existing gateway import dependency; no packages were downloaded for these checks.

Native Mac browser layout, real local-model JSON action compliance, useful GPU
throughput, sustained memory pressure, GPU cancellation, model startup/draining,
real VPN research and native upgrade/approval acceptance are NOT RUN. Closing a
host socket does not prove GPU work immediately stopped. Quarantine deletion is
logical deletion, not guaranteed forensic erasure or backup removal. Village
encrypted backup/restore and complete source deletion remain unfinished; the PR
stays draft and real personal exports should remain unimported.

No GitHub Actions were dispatched or rerun. The publishing commit contains
`[skip ci]`; no merge is part of this preview update.

## Village infrastructure preview, 19 October 2026

Development release `2026-10-19-village-infrastructure-preview` extends the
Agent Village branch; it is not a new deployment variant or a claim that
`main` or the owner's Mac has been updated. The same canonical ZIP is rebuilt.

The facilities add approved, versioned workshop content; project-scoped durable
notices and suggestions; and practice cases that pin a workshop revision and
fabricated input hashes. The host supplies identity and project scope. Native
approval is required for Build publishing and preparation, and final workshop
approval remains an owner CLI action. No contributed code is executed by the
storage service. Practice folders are not OS sandboxes.

Local checks:

- Village/archive and facilities Python: 18 passed. Covers exact approval and
  replacement, withdrawal, project isolation, explicit practice-copy links,
  replay receipts across restart, current scope/revision checks, concurrent
  revocation, bounded inputs, inert malicious source, and migration rollback.
- Captain setup Python: nine passed; installer Python: 26 passed.
- Captain and existing OpenCode policy JavaScript: 46 passed. Includes the real
  Python/SQLite subprocess bridge with synthetic native sessions and approval
  doubles, rejected/missing approval, Plan refusal and approval-time mode change.
- Installer build, full contents/permissions/manifest comparison, deterministic
  rebuild, Python compilation and JavaScript syntax checks are required for the
  preview artifact. Results are recorded with the pull request.

Existing encrypted Village export/restore and source deletion are unfinished.
Native Mac installation, actual OpenCode approval UI and local-model use remain
pending; follow [the acceptance sequence](VILLAGE-INFRASTRUCTURE.md#acceptance-on-your-mac).
No hosted CI run was dispatched for this change. The earlier release records
below are historical evidence, not certification of this preview.

## Earlier integrated release

**Release:** `2026-10-14-captain-hardening-2`
**Date:** 14 October 2026
**Canonical source:** `main`
**Installer:** `downloads/Mac-Local-AI-Automated-Installer.zip`

## Captain implementation

The release includes native worker cohorts, a task board and peer messages,
shared text admission, exclusive model barriers and MiniCPM desktop setup.
Authoring tests ran 199 installer cases (5 native/environment cases skipped),
122 gateway cases and 84 JavaScript cases: 400 passed, 5 skipped, no failures.
They use simulated model responses and temporary local HTTP services. These
results verify host behaviour; they do not measure local-model quality or GPU speed.

The original captain revision (`5e94114`) passed the pinned native desktop
runtime build and macOS PDF jobs but had a runner-uptime-dependent idle test
failure. The audited revision (`ceb8ce6`) passed all three GitHub jobs, including
the actual pinned OpenCode binary against synthetic local inference: worker
overlap, native tool execution, reports and retirement verified without model
weights. The final update adds regressions for audio-release failures during
mode changes and cleanup errors that must not skip other owned releases.
`Check Captain.command` runs real OpenCode/model dispatch, evidence
reading, reports and retirement on the new Mac. Full installation invokes it
alongside existing native acceptance. Owner-Mac performance, real MiniCPM tool
reliability and five-slot memory pressure remain pending.

Read [Captain and workers](CAPTAIN-AND-WORKERS.md) for the active architecture.
Read [the environment audit](ENVIRONMENT-AUDIT-2026-10-14.md) for corrections and remaining limits.
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
