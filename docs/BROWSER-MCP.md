# VPN-only Playwright browser MCP

This is an **opt-in** addition to the existing SearxNG + reader stack. It uses Microsoft's official headless Chromium MCP container and **shares Gluetun's network namespace**. It never opens a host-side Chromium connection to the public Internet, and does not replace the SearxNG search and lightweight reader operations.

## Install / activation on the Mac

1. Update your local installer source from this branch and rerun the normal installation so the new helper files are copied into `~/LocalAI-Automated/control`. The project is **not** deployed to the Mac merely by committing GitHub code.
2. Stop Local AI, keep Docker Desktop running, and make sure VPN web access is enabled via `Enable Web Access.command`. Proton WireGuard credentials remain local.
3. Run `~/LocalAI-Automated/Enable Browser.command`. The helper downloads Microsoft's official MCP container, records its immutable digest alongside existing Docker image locks, adds the browser to the VPN Compose configuration, starts the services and verifies a JSON-RPC MCP initialize exchange.
4. Restart LOCAL AI. Enable **Playwright browser** in the chat's Integrations menu. For the Work Agent, use `Start Work Agent.command`; the tool is included in its MCP connections when both VPN web and browser are enabled.
5. Run `Check Browser.command` to verify the MCP handshake. Then test navigation to a simple public page, a JavaScript-rendered page, and a download under `~/LocalAI-Automated/web/browser-outputs`. Verify public outbound traffic exits the Proton tunnel before trusting the setup. Test tunnel failure to ensure browser access stops. These live acceptance tests have not been performed.
6. Stop LOCAL AI and run `Disable Browser.command` to remove the optional browser container without erasing the saved browser profile or downloads.

The companion browser service publishes only `127.0.0.1:8931` on the Mac via Gluetun. No port is opened to Tailscale or the LAN. The Compose service is pinned by immutable image digest, runs with a memory limit of 768 MiB, one CPU, headless Chromium, no extra capabilities and a limited output directory. Browser pages still load external scripts and resources through the VPN. Network isolation is not the same as browser safety: Playwright MCP is **not a security boundary**.

## User data and permissions

The Chromium profile is stored in `~/LocalAI-Automated/web/browser-profile`, and output files in `~/LocalAI-Automated/web/browser-outputs`. Both are local, owner-restricted directories, and are not automatically transferred into the encrypted AI Workspace. Browser sign-ins and cookies can persist. Use a dedicated browser login and avoid bank, payment or admin accounts until isolation and approval checks pass. The browser is a shared local MCP endpoint: no per-chat isolation is guaranteed.

The Work Agent allows snapshots and diagnostics, but requests native approvals for navigation, input and actions. The chat uses Open WebUI's experimental tool approval setting; **it must be verified in a saved chat** before permitting writes, uploads, account changes or purchases. Approval prompts are not a backend authorization or sandbox boundary. The MCP endpoint itself has no bearer-token guard; any process on the Mac that can access the loopback endpoint may invoke it. Do not expose port 8931 through a network forwarding service.

Do not attempt host-side fallback if the VPN is down. Keep the native Open WebUI web fetching disabled. Use SearxNG/reader for simple retrieval, browser only for dynamic sites and interaction. Page content and accessibility text are untrusted and must not be treated as instructions.

## Verification status

The repository includes `installer/tests/test_browser.py` for configuration invariants and connection registration. No real Mac deployment, actual container start, browser browsing test, tunnel-drop test, or UI approval test has yet been performed. A test file in the repository is not evidence that it passed.

## Important limitations

- The Docker implementation is headless Chromium, not a visible Safari window.
- The container consumes memory while running even if Chromium is not actively rendering. Disable it when not needed.
- Profile persistence is intentional but introduces cookie/security risks.
- Generated downloads are on disk and need separate, explicit transfer to AIOffice or the vault.
- A verified browser exit IP, stronger private-IP/SSRF isolation, MCP endpoint authentication and destructive-action enforcement are still outstanding hardening tasks.
