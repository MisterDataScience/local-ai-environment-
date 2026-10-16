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
  Compose to become ready, before attempting VPN-backed browsing.
- Reuses existing Proton/Gluetun images and refuses ordinary-network
  fallback if the VPN is unavailable; periodically checks and restarts only
  the managed VPN stack.
- Opens Tailscale when remote access is enabled. Every two minutes, it checks
  the expected tailnet hostname and private Serve routes (443, 8443, 10000),
  recreating **only missing owned routes**. Unexpected proxy targets or a
  changed hostname are left untouched. Any newly detected public Funnel rule
  on managed ports forces the supervisor to stop instead of remaining exposed.
- Restarts a crashed Captain only when the gateway is healthy and Normal/Max
  mode allows it. Its child-process ownership checks avoid terminating
  unrelated processes after a PID has been reused.

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
`shared-llama.log` and `install.log`, plus
`captain-install-readiness.json` and `remote-acceptance-report.json`.
Treat every off-device/reboot/physical result as pending until observed.
Do not paste logs containing secrets into public issues.
