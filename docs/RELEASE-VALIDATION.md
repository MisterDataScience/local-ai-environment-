# Integrated release validation

## Current source and package status

The current consolidated release is `2026-11-09-mac-native-recovery-1`.
See the [repair and acceptance record](MAC-REPAIR-CONSOLIDATION-2026-11-09.md)
for the integrated fixes, owner-reported Mac result and exact limits of that
result. The matching ZIP is rebuilt and verified against the current source.
The earlier candidate and release sections below are historical records.

## Consolidated repair authoring checks, 9 November 2026

| Check | Result |
| --- | --- |
| Installer, Python 3.11.17 | 556 run, 541 passed, 15 skipped |
| Gateway | 154 passed |
| JavaScript with pinned Effect codec | 167 run, 165 passed, 2 skipped |
| Release-script tests | 8 passed |
| Python compilation and launcher shell syntax | Passed |
| Exact archive/source hashes, modes and ZIP integrity | Passed |
| Reproducible installer rebuild | Passed |
| Pinned native Linux OpenCode executable | Verified download; SIGABRT before version; blocked here |
| Owner-reported repaired Mac core and conversation check | Passed on the repaired installed copy |
| Fresh rebuilt-archive installation, optional features and physical journeys | Not performed here |

The skipped authoring fixtures require macOS PDFKit/Vision or explicit
C/Wasmtime compiler/player dependencies. The optional Playwright browser
fixture was excluded. The real format encoder test uses Effect 4.0.0-beta.83.
No hosted Actions were dispatched. The publication workflow remains manual-only.

The native conversation gate exercises both stopping and resumption. It uses
one new tool-denied session, four forced compactions, a completed READY reply
and a queued genuine request requiring DONE. A summary is not allowed to
substitute for the original pending request. Local probe fixtures deliberately
test failures as failures; the owner-Mac pass is recorded separately.

## Historical modular candidate status

The modular core candidate rebuilds the checked-in ZIP from its current source.
The release identifier is `2026-11-03-modular-core-candidate-2`, with per-file
SHA-256 hashes and executable launcher permissions. This establishes package
freshness, not native acceptance on the owner's Mac. Historical validation
sections below describe their own snapshots.

Core and optional modules record native acceptance separately. See
[modular installation](MODULAR-INSTALLER.md#native-acceptance-still-required).
PRs #39 and #40 were inspected but are not merged by this work; their useful
macOS path/xattr fixes are incorporated into the coherent implementation.
Unfinished Pixel Art PR #38 is excluded.

The release workflow remains manual-only. Hosted runner allowance was not used.
A publication from main still requires its explicitly selected Linux and two
macOS release gates. Local source tests and archive checks do not replace them.

`python3 scripts/build_installer.py --check` compares exact contents, permissions
and manifest against the checked-out source. Any stale archive must fail. Rebuild
after source/documentation changes and verify again before delivering a package.

## Launcher correction, 3 November 2026

Named core, full and MiniCPM launchers invoke their common helper through
`/bin/bash`, matching the existing Web/Remote aliases. A regression exercises all
five aliases with a non-executable helper and a folder name/arguments containing
spaces. The package includes Apple's per-item approval instructions for unsigned
downloads. No quarantine attributes, Gatekeeper settings or binary verification
rules are changed by this correction. Native Finder/Gatekeeper acceptance on
the owner's Mac remains unverified.

Validation: 30 installer tests, one package construction test, all launcher shell
syntax checks and the current archive/source and reproducibility checks passed.
The full 2 November suite below was not repeated for this launcher-only change.

## Modular candidate authoring checks, 2 November 2026

| Check | Result |
| --- | --- |
| Installer tests | 475 run, 459 passed, 16 skipped |
| Gateway tests | 144 passed |
| JavaScript policy/workflow tests | 110 run, 109 passed, 1 skipped |
| Release-script tests | 7 passed |
| Python compilation and shell launcher syntax | Passed |
| Current ZIP contents, hashes, permissions and reproducible rebuild | Passed |
| Pinned Linux OpenCode native protocol | Blocked: verified binary exits with SIGABRT before `web --help` in this authoring environment |
| Owner Mac core, resumed installation and feature acceptance | Not run |

The 17 skips cover four macOS PDFKit/Vision cases, the pinned WebUI-wheel
compatibility fixture, eleven C/Wasmtime compiler fixtures and one exported C
player fixture. The optional Playwright conversation-browser test was not run.
No model weights, owner accounts or owner Mac were used to obtain the source
results. Hosted Actions were not dispatched. The native OpenCode failure is
separate from the passing synthetic protocol and JavaScript policy tests.

New regressions cover minimal core and existing-settings recovery, missing WAV
resumption, rejected Discord credentials, lock conflicts, unsafe/corrupt receipts,
source-change invalidation, dependency gating, exact installer discovery, MCP
session/response handling, interrupted VPN-test recovery and managed Discord
bridge reuse. Core retains the real model/worker tests as installation gates;
none of these unit fixtures satisfies those gates.

## C studio release, 20 October 2026

Release `2026-10-20-village-studios-1` adds integrated institutions, private studio
collections, source founding, prepared Lead Designer/staff and memory-map
proposals, bounded C workstations and a 320 × 180 offline player. Original
sources are preserved, while publication and lasting memory/access changes
require final owner review. The studio remains a C workbench; Pyxel was assessed
as an alternative and was not installed or substituted.

Validation: 375 installer tests (370 passing, five skipped), 136 gateway tests,
92 JavaScript tests and seven release-script tests, totalling 605 passing checks.
The skips remain the four native Apple PDF cases and pinned WebUI-wheel case.
Real C fixtures exercise Wasmtime through the worker process, deterministic
updates, checkpoints, drawing scratch memory, sprite transparency/scaling, tiles,
bitmap text, fuel traps, forbidden system imports and machine limits. The exported
player's JavaScript worker executes real compiled Wasm and restores state/pixels.
SQLite and HTTP tests cover founding, private access, final approvals, memory
maps, source withdrawal and authenticated owner controls. Model answers use
fixtures; their quality is not inferred from these tests.

The native test compiler is Clang from WASI SDK 27; deployment pins Zig 0.14.1
and Wasmtime 38.0.0. The resumed authoring environment required reinstalling the
test Wasmtime wheel after its saved native library crashed on import. Tests were
rerun using the restored dependency. No production dependency was changed for it.
The final regression run exposed a retained SQLite inventory connection that could
change a corrupt-source erasure preview when garbage-collected. Inventory now
closes it explicitly; a regression verifies stable previews across collection.

Python and owner/player JavaScript syntax pass. Exact installer contents,
permissions, manifest and byte-identical rebuilding are verified. Mac sandbox
execution, production Zig compilation on the Mac, native installation, browser
layout and sustained model performance remain target-platform acceptance work.
The owner's two games were not supplied and are not represented as tested.
No GitHub Actions were dispatched. See [the studio guide](INSTITUTIONS-AND-STUDIOS.md)
for the operating flow, compatibility limits and broad source-erasure scope.

## Consolidated Village release, 19 October 2026

Release `2026-10-19-integrated-village-1` combines installer hardening, Commons,
layered resident memory, prepared resident management, local founding review,
encrypted Village backup/restore and managed source erasure in the single main
installer. Founding prepares cited proposals and specialist identities; lasting
publication and prompt maps still require final owner approval.

Local validation: 357 installer tests (352 passed, five skipped), 135 gateway
payload tests, 90 JavaScript tests and seven release-script tests. Total: 584
passed, five skipped. Skips cover four Apple PDFKit/Vision cases and one pinned
WebUI-wheel compatibility case. The optional browser suite was attempted but
could not run because Chromium is not installed on this authoring host.
Python compilation, owner-page JavaScript syntax and generated owner-launcher
shell syntax were checked. The release builder checks exact packaged source,
permissions and manifest; repeat builds are byte-identical.

New checks exercise real SQLite and ZIP recovery, source tombstones across
restore/local-ledger loss, interrupted deletion recovery, stale previews and
reader locks, original import bytes, exact cited proposals, private publication,
local inference guards, foreground cancellation and bounded format repair.
Cryptomator mounts and model output use fixtures; no real Mac installation,
mount semantics, GPU performance, native permission dialogs or browser layout
acceptance is claimed. See FOUNDING-AND-RECOVERY.md for normal use and the broad,
explicit source-erasure scope. No GitHub Actions were run. The retained workflow
is manual-only and release commits suppress CI.

All sections below describe earlier releases and are historical.

## Prepared resident management, 19 October 2026

Release `2026-10-19-resident-management-preview` removes routine manual agent/map
setup from the user flow. The host seeds five baseline residents. Captain Build
can prepare complete create/revise/retire/map proposals using a host-assigned
identity and durable replay receipt. Proposal preparation needs no separate
native permission prompt because it cannot publish, activate, expand grants or
run inference. Exact final owner review in the dashboard remains required.
Workers and Commons cannot call Captain lifecycle management.

Dashboard maintenance prepares map suggestions from approved own memories,
material pointers and Library titles matched against approved role/tag/profile
terms. It preserves valid existing pins, stages changed bindings and source
removals, suppresses identical rejected drafts, and expires pending content.
This is bounded deterministic candidate preparation, not semantic understanding
or a new model/background job. No pending map enters a resident packet.

142 focused checks pass: nine management, 16 Commons core, eight layered-memory,
18 Village/facility, nine Captain setup, 26 installer, six Commons HTTP/transport,
49 Captain/OpenCode JavaScript and one builder regression. New cases cover no
manual baseline creation, automatic prepared maps, separate final review, no
self-approval, stale parent/map refusal, explicit approved activation, revision/
retirement, duplicate/rejected/expired proposals, real host receipts and native
worker tool denial. The owner API prepares/reviews a map with zero inference.
Python/JavaScript syntax and deterministic installer/source verification are
checked for publication. No hosted Actions run is dispatched or rerun.

Normal instructions, optional manual overrides, developer acceptance and remaining
engineering work are now separate documents. Full encrypted Village recovery,
complete source deletion and automated founding-corpus analysis remain unfinished
engineering, not owner setup tasks. Native Mac/model/browser acceptance remains
unrun on this authoring host. See VILLAGE-STATUS.md and
VILLAGE-DEVELOPER-ACCEPTANCE.md for the exact boundary.

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

## Synod construction and archive, 24 October 2026

The Synod is included without founding and uses the existing local studio dispatcher.
The construction contract, adapter limits and archive schema are described in
[The Synod](THE-SYNOD.md). The initial executable adapter is limited to text studios;
custom runtime repairs and new tool capabilities remain explicit construction blockers.

Authoring checks: 11 Synod controller tests, 83 existing studio tests (11 native/runtime
cases skipped), 25 Captain JavaScript tests, 29 installer tests, 9 Village recovery/privacy
tests, 7 context policy tests and the deterministic installer packaging test. These use
scripted model responses and real local queues/storage, not real-model quality claims.
Python compilation, JavaScript syntax, HTML control IDs and installer/source verification
also pass. The full installer suite has environment import blockers because `requests`
is unavailable. Browser rendering could not run because the Playwright Chromium binary
is absent. Native Mac/model acceptance remains unrun. No hosted CI was triggered.
