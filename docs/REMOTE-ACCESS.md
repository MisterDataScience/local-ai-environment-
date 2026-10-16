# Private Captain access from iPad and Windows

## Provisioned automatically by the Captain installer

Run **Install Local AI.command** once on the 32 GB Apple Silicon Mac.
No second remote installer or Enable Remote Access command is required.

During installation, the installer downloads and checks the signed standalone
Tailscale application if it is missing. It opens the Tailscale Mac app: the owner
approves its system/network extension, signs into their personal Tailscale
account, and enables HTTPS in the tailnet if prompted.

The installer then configures **Tailscale Serve**, NOT Funnel, with these exact
private HTTPS endpoints:

| Endpoint | Mac-only backend | Purpose |
| --- | --- | --- |
| `https://MAC.TAILNET.ts.net:10000` | `127.0.0.1:4096` | **Actual Captain OpenCode** interface with independent HTTP Basic Auth |
| `https://MAC.TAILNET.ts.net` | `127.0.0.1:8081` | Standard Open WebUI chat |
| `https://MAC.TAILNET.ts.net:8443` | `127.0.0.1:8002` | Generated media only |

The installer saves the precise private URLs to
`~/LocalAI-Automated/Remote AI Address.txt`. Its readiness checks require
actual Tailscale route status, a **401 response from unauthenticated Captain
requests**, and successful authenticated retrieval of the actual native Plan
and Build agent list. Cross-origin redirects of requests containing the
Captain password are blocked. It also checks the regular chat health
endpoint and the media-only endpoint isolation.

This is a private personal tailnet route, not public hosting or whole-Mac
network forwarding. The Captain is still bound to loopback. The independent
Captain username/password are stored locally in
`~/LocalAI-Automated/control/captain-ui-auth.json` with owner-only permissions.
The installer prints them when opening the local Captain. Later,
`Open Captain.command` displays them locally when needed. **Do not paste
this password into a public document or cloud chat.**

## First use from another device

Install Tailscale on each iPad and Windows device that should connect.
Sign into **the same personal tailnet** and open the saved **Captain** URL in
Safari or your Windows browser. You should be asked for the Captain username
and password. Ordinary WebUI is available at the **Chat** URL but **does not
expose the Captain orchestration workflow**.

Restrict your Tailscale ACLs to your own devices/users. Other users allowed
to reach the chat endpoint can access the single-user WebUI and its shared
chat history. This solution does not configure Open WebUI multi-user
authentication. Allow TCP 10000 for Captain, 443 for chat and 8443 for
generated media only to the devices/users intended to use them. The remote
Tailscale device must be connected to the personal tailnet.

**The Mac-side HTTPS tests are not an off-device browser test.** Confirm
Captain login, message generation, agent delegation, local approvals and
denial behaviour from Windows or iPad before marking the first installation
fully accepted.

## Security and recovery

- Public Tailscale Funnel, exit nodes, public router forwards, and extra
  subnet routes are never enabled. Any conflicting Serve route or existing
  Funnel rule on the three managed ports blocks installation.
- The installer preserves unrelated Tailscale routes and reverses only
  newly created routes if setup fails.
- Existing Tailnet sign-in is reused. The installer does not store a Tailscale
  password or auth key.
- The Mac must remain awake and online. Login startup is managed via
  `launchd`, but headless reboot/login, sleep/wake and wake-on-network
  are still unverified on the owner's hardware.
- `~/LocalAI-Automated/remote-acceptance-report.json` explicitly marks
  the Windows/iPad browser acceptance as pending until observed.
- The older Enable/Disable Remote Access helper commands remain available
  **for repair or deliberate deactivation**, not as a mandatory installation
  procedure. Disable removes only the exact three routes managed by LOCAL AI.

See [deployment](DEPLOYMENT.md) and [release validation](RELEASE-VALIDATION.md).
