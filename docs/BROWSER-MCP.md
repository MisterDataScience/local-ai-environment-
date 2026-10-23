# VPN-only Playwright browser MCP

The standard Captain installation provisions the Playwright browser alongside the SearXNG search and reader stack. Browser use remains opt-in in ordinary chats: select the integration only when a task needs a dynamic site or browser interaction. Playwright uses Microsoft's official headless Chromium MCP container and shares Gluetun's VPN network namespace. It never opens a host-side Chromium connection to the public Internet.

## Install / activation on the Mac

### Standard Captain installation

1. Run **Install Local AI.command** for a new installation. It invokes the Captain setup, installs and verifies Docker Desktop, configures VPN-only search and page reading, then pulls the pinned Playwright MCP image and verifies its JSON-RPC connection. Docker approval/licence acceptance and a Proton Free WireGuard private key are required during setup.
2. For an existing installation, update the installer source from `main` and rerun **Install Local AI.command**. A GitHub commit alone does not deploy the changed installer files to the Mac.
3. Restart LOCAL AI after installation. In an ordinary Open WebUI chat, select **Playwright browser** from the chat's Integrations menu. Search and page reading use the separate **Local AI VPN retrieval** integration. The Work Agent receives Playwright when both VPN web and browser are configured; launch it with **Start Work Agent.command**.
4. Run **Check Browser.command** to verify the MCP handshake. Then test navigation to a simple public page, a JavaScript-rendered page, and a download under `~/LocalAI-Automated/web/browser-outputs`. Verify public outbound traffic exits the Proton tunnel before trusting the setup. Test tunnel failure to ensure browser access stops. These live acceptance tests have not been performed.

### Existing partial or non-Captain installations

The helper commands remain available for installations that have VPN web access but have not provisioned the browser. Stop LOCAL AI, keep Docker Desktop running, and enable VPN web access first. Then run `~/LocalAI-Automated/Enable Browser.command`. It downloads the pinned MCP image, adds the browser to the VPN Compose configuration, starts the services and verifies the MCP handshake. Restart LOCAL AI and select **Playwright browser** in the chat Integrations menu. Run **Disable Browser.command** to remove the optional browser container while retaining the saved profile and downloads.

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
