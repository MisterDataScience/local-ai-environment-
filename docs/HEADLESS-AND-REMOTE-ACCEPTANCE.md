# Headless Mac resilience and remote first-use acceptance

## What now starts and recovers automatically

The normal Captain installer registers a user-level `launchd` LaunchAgent
which starts the LOCAL AI supervisor **after that user signs in**.

While running, the supervisor:

- Launches a separate, unprivileged `caffeinate -i -s -w SUPERVISOR_PID`
  process. It prevents idle system sleep on an AC-powered Mac, but does not
  keep the display awake or override intentional Sleep, shutdown or restart.
  The sleep assertion ends when the supervisor exits.
- Opens signed Docker Desktop and waits for its local Unix-socket Engine and
  Compose to become ready, before attempting VPN-backed browsing. If its
  engine or app is later quit, the VPN recovery loop reopens Docker before
  restarting the managed VPN stack.
- Reuses existing Proton/Gluetun images and refuses ordinary-network
  fallback if the VPN is unavailable; periodically checks and restarts only
  the managed VPN stack.
- Opens Tailscale when remote access is enabled. One background worker checks
  whether the app is connected and reopens it if necessary, without storing
  sign-in credentials or selecting a different account. It then checks
  the expected tailnet hostname and private Serve routes (443, 8443, 10000),
  recreating **only missing owned routes**. Unexpected proxy targets or a
  changed hostname are left untouched. Each completed attempt has a two-minute
  cooldown, and attempts never overlap. Any newly detected public Funnel rule
  on managed ports forces the supervisor to stop instead of remaining exposed.
- Restarts a crashed Captain only when the gateway is healthy and Normal/Max
  mode allows it. Its child-process ownership checks avoid terminating
  unrelated processes after a PID has been reused.
- Probes Captain's authenticated `/agent` control API every 30 seconds with
  a three-second timeout. Three consecutive failures retire its owned process
  group. The existing launcher retries after a 30-second cooldown, subject to
  gateway readiness and Normal/Max mode. Startup and wake get 60 seconds of
  grace. A successful probe resets the failure count. Generation duration and
  pending approvals are not used as failure signals.
- Includes the gateway in repeated core health checks. A persistent gateway
  hang fails the supervisor, allowing launchd to restart after owned service
  cleanup. A failed Captain readiness check cleans up that launch attempt
  before a retry.

These recovery paths are implemented and unit-tested, but real macOS
login and reconnection acceptance are **pending**.

## Crucial limit: boot before login

The app is a **LaunchAgent, not an always-on root LaunchDaemon**. If FileVault
or macOS requires user sign-in after boot, neither the Captain nor Tailscale
is guaranteed to start until the owner authenticates locally.

No automatic login, FileVault bypass, stored Mac login password, unscoped
root service, or permanent `pmset` change is installed. That restriction is
intentional. After a power loss or restart, the user may need to unlock and
log into the Mac. An always-on remote Mac also requires stable AC and network.

## Required observed first-use tests

1. From Mac: open Captain at localhost 4096 and the Tailscale HTTPS URL.
   Check incorrect password is denied, correct password opens the same
   native Plan/Build agents, and the remote browser receives the correct
   event stream. Confirm Tailscale ACL limits access to your own devices.
2. From **Windows** and **iPad**, each signed in to your personal Tailscale
   account: open `https://MAC.TAILNET.ts.net:10000`, authenticate, create a
   session, complete a real Captain delegation, approve/deny a proposed
   action and verify the result. Ordinary WebUI uses the separate 443 URL.
   CI's native browser-origin test is not a substitute for this step.
3. Close and restart Tailscale while the Mac remains awake. Confirm the
   expected private routes recover and that unrelated Serve entries are
   unchanged. Confirm a blocked client or public Funnel configuration does
   not obtain Captain access.
4. Restart Docker Desktop or its engine. Confirm VPN-only browser operations
   recover without any direct-network fallback.
5. Allow macOS display sleep and idle overnight; verify the Mac remains
   tailnet-accessible with the supervisor running. Then intentionally sleep
   the Mac to confirm the documented non-wake limit.
6. Reboot and separately verify the FileVault login requirement, LaunchAgent
   restart, the existing Cryptomator vault unlock, tailnet reconnection and
   backup restoration.

## Logs

Use the existing local `~/LocalAI-Automated/logs/` files:
`login-start-error.log`, `gateway.log`, `captain.log`,
`shared-llama.log`, `remote-recovery.log` and `install.log`, plus
`captain-install-readiness.json` and `remote-acceptance-report.json`.
Treat every off-device/reboot/physical result as pending until observed.
Do not paste logs containing secrets into public issues.

## Captain freeze watchdog validation

The managed OpenCode server now inherits its wrapper's private process group.
The supervisor can stop that owned group even when the wrapper itself cannot
forward a signal. Manually invoked unmanaged Work Agents keep their existing
independent process group. A managed launch outside a private wrapper group is
refused to protect the shell and unrelated processes.

The watchdog never selects a process by a listening port. It acts only on the
Captain subprocess retained by this supervisor. A failed/transitioning gateway
or Gaming mode resets the failure streak and blocks watchdog restarts. Wake
grace compares elapsed wall and monotonic time so slow Tailscale work is not
mistaken for sleep. A large forward system-clock correction may also grant
grace. Tailscale recovery and remote HTTPS verification now run in a separate
worker process, so their network/CLI waits no longer delay monitoring ticks.

Local regression tests exercise a real authenticated loopback HTTP server that
stops responding, failure thresholds/resets, grace/mode boundaries, retirement
of only the tracked Captain, and termination of a synthetic stuck wrapper plus
its child in a real private process group. These are not native OpenCode/Mac
freeze-recovery results. Verify actual browser reconnection, approval behavior
and session state on the Mac before release. Interrupted turns are not replayed
automatically; completed side effects are not resubmitted by the watchdog.

Linux validation for this watchdog change: 265 installer tests discovered
(261 passed, four Apple-only tests skipped), 127 gateway tests passed and 84
JavaScript tests passed. Compilation, shell syntax and the local installer
archive verification passed. The ten watchdog-specific regressions include the
real HTTP and process-group tests above. Hosted CI remains unused and the
published installer remains unchanged until the native release gates pass.

## Nonblocking Tailscale recovery

The supervisor polls one background repair process without waiting for its
network or CLI work. It starts that process after local services are ready.
The initial pre-start public-Funnel guard remains synchronous, before services
are exposed. The guided installer's mandatory private-access checks still
gate its readiness receipt.

The worker reopens the installed Tailscale app, checks the exact configured
hostname and reconciles only missing owned routes. It verifies private HTTPS
on its first successful run, after a repair, and after any prior failed check.
Transient failures leave local health monitoring and the Captain watchdog
running. A new attempt starts no sooner than 120 seconds after the previous
one finishes. No provider credentials or proxy overrides are inherited by the
worker.

A public Funnel rule has its own fatal result type/exit code. The worker also
signals its verified direct parent so shutdown can interrupt a busy monitoring
loop. The supervisor's security-stop signal bypasses ordinary retry handlers;
completed worker status provides a second detection path. An unrelated or
reused PID is not notified. Hostname conflicts never select a new account or
overwrite another service's routes.

On shutdown the supervisor stops the worker's private process group, allowing
a bounded cleanup grace before escalation. The worker also cancels its group
if its parent disappears. Existing route rollback remains in place. A failure
stopping the worker does not skip the remaining local-service shutdown.
Installer and worker reports use unique, private atomic temporary files.

Linux validation: 13 new regressions passed, including a real stalled worker
while health checks continue, a real fatal-notification signal, concurrent
report writers, no overlapping repairs, cooldown/retry and parent/shutdown
boundaries. The full installer suite passed 274 tests with four Apple-only
skips (278 discovered); 127 gateway and 84 JavaScript tests passed. Compilation,
shell syntax and local installer archive verification passed. Actual macOS
Tailscale crash/reconnect/shutdown acceptance remains pending. Hosted CI was
not triggered and no replacement installer was published.


## Native approval acceptance extension

`scripts/check_native_captain.py` now runs five additional native scenarios
through `scripts/native_approvals.py` before its existing parallel-worker test:

- Build approves a temporary command once, then repeats the identical command
  in the same session and requires a new approval. The harness removes only
  its own first marker before the repeat, and examines only new native history.
- Build rejects a command; its marker must stay absent and native tool history
  must record rejection.
- A delegated Captain coder requests approval and executes only after approval.
- A delegated Captain coder receives rejection; no marker may be written.

Every scenario requires a real pending native bash permission describing the
exact command. The harness observes a blocked request and absent marker before
replying. Missing and incorrect Basic authentication must fail both permission
listing and approval replies, leaving the original prompt pending. The real
SSE stream must deliver matching `permission.asked` and `permission.replied`
events for the correct owner. Worker ownership is checked against the parent's
actual child sessions, and completed workers must retire. Replayed/stale reply
IDs must return HTTP 404. No production permission setting is relaxed.

The synthetic inference endpoint only returns model messages and tool calls.
The actual OpenCode binary must create prompts, execute or reject the command,
publish events and record native history. Commands write a fixed marker only
inside a newly created temporary acceptance project. No model weights, user
project files, real account credentials or external inference are used.
Authenticated requests include the simulated private tailnet Host/Origin used
by the prior native check. This is not a Windows/iPad browser or live Tailscale
test, and does not prove that a remote UI renders a worker's approval card.

Local harness regressions exercise successful and rejected scenarios, deliberate
early execution, missing effects, rejected commands that still write, duplicate
actions, authentication bypass, wrong session ownership, repeat-turn isolation,
synthetic worker message progression, and a real local HTTP SSE reader with
bounded shutdown. These are tests of the acceptance harness, not native
approval evidence. Six approval-harness tests and one archive regression passed.

The final native attempt on this Linux host still exits with SIGABRT while
running the pinned OpenCode 1.18.34 `web --help`, before the server or any of
these scenarios starts. A clean environment showed the same startup abort.
System-call tracing is unavailable in this environment. Do not mark native
approval acceptance passed based on these regressions.

Run on a compatible host with the pinned, checksum-verified binary:

```bash
python scripts/check_native_captain.py --binary /path/to/verified/opencode
```

The existing manual-only workflow invokes the extended check when deliberately
dispatched; no dispatch or rerun was requested for this change. Native execution,
then actual Windows/iPad approval and denial over Tailscale, remain release
blockers.
