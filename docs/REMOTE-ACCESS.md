# Private access from iPad, phone and Windows

Optional Tailscale setup is included in the installer. The Mac runs all models; other devices open the same Open WebUI and use the same local chat database.

## Install with remote access

Download the updated automated installer ZIP and extract it into Downloads. Run:

```bash
/bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI with Remote Access.command"
```

The ordinary `Install Local AI.command` remains local-only. The remote wrapper passes `--remote-access` to that same installer; all model installation and acceptance stages remain the same.

After the local installation passes, the optional remote stage:

1. Reuses an existing `/Applications/Tailscale.app` if present, without replacing its variant or signing into another account.
2. Otherwise downloads the official standalone Tailscale 1.102.4 package. It checks the installer signature against Tailscale's signing team and macOS Gatekeeper, then requests macOS administrator approval to install it.
3. Opens Tailscale. You approve its system/network extension and sign in to your personal Tailscale account. The installer waits up to 15 minutes for a connected MagicDNS hostname.
4. Configures private Tailscale Serve HTTPS proxies for chat and generated media. Tailscale may ask you to enable HTTPS for your tailnet; follow its displayed approval flow.
5. Saves the private addresses in `~/LocalAI-Automated/Remote AI Address.txt` and starts Local AI.
6. Checks the HTTPS chat health endpoint and media routing from the Mac. This is not a substitute for a browser check from another device.

No Tailscale password or auth key is copied into the Local AI configuration or repository. macOS approval and Tailscale sign-in are one-time interactive steps; they cannot be completed by this authoring environment.

If Tailscale requests a reboot, complete it and resume the installer or run the generated Enable Remote Access command after login. The remote stage does not claim success without confirming its Serve configuration.

## Add your other devices

Install Tailscale on the iPad/phone and Windows laptop from [Tailscale's official downloads](https://tailscale.com/download). Sign in to the same personal account and approve/connect each device. Open the **Chat** address saved on the Mac in Safari or your Windows browser, then bookmark it.

Example addresses, not your actual hostname:

| Purpose | Example |
| --- | --- |
| Chat | `https://mac-mini.example.ts.net` |
| Generated image/video files | `https://mac-mini.example.ts.net:8443/media/FILE` |
| Local chat on the Mac | `http://127.0.0.1:8081` |

The remote device needs access to Tailscale TCP ports 443 and 8443 under your tailnet's permissions. A newly created personal tailnet normally starts with broad access among its devices; if yours has custom restrictions, permit these two ports only for your intended devices/users.

This installation keeps Open WebUI's existing single-user mode and chat database. Access is controlled by Tailscale membership and tailnet permissions, not a second WebUI password. Anyone permitted to access these routes can use the same chats and media. Use a personal tailnet with only the devices/users you intend to admit. Open WebUI documents that switching an existing single-user database to multi-account mode is not supported; this feature does not attempt that migration.

## What is exposed

| Private HTTPS route | Local target | Scope |
| --- | --- | --- |
| Port 443 | `127.0.0.1:8081` | Open WebUI |
| Port 8443 | `127.0.0.1:8002` | Generated files only |

The media listener rejects the chat API, model listing, health endpoint, POST requests and traversal outside the media folder. The gateway API remains on loopback port 8001 with its existing bearer key. Ollama and ComfyUI remain loopback-only.

The helper never enables Tailscale Funnel, exit nodes, subnet routes or public router port forwarding. It refuses conflicting Serve routes and existing Funnel access on the two managed ports. It preserves unrelated services and rolls back newly created routes if configuration fails. Serve background configuration persists across Tailscale restarts; Local AI itself still uses the foreground Terminal supervisor.

Tailscale provides access to the Mac. Proton/Gluetun is a separate future feature for outbound AI web retrieval. This addition does not implement VPN search.

## Enable or disable later

After installing the updated bundle, the generated commands are:

```bash
/bin/bash "$HOME/LocalAI-Automated/Enable Remote Access.command"
/bin/bash "$HOME/LocalAI-Automated/Disable Remote Access.command"
```

Stop Local AI before changing remote configuration, then restart it. Enabling later runs only Tailscale setup; it does not reinstall or download AI models. Disabling removes only the two matching Local AI Serve routes and disables remote media links. It does not uninstall Tailscale or reset other Serve services.

An older installation needs the updated installer run once to receive these helper commands. A hostname change also requires rerunning Enable Remote Access. The hostname is saved after setup, not automatically changed.

## Checks and limitations

`~/LocalAI-Automated/remote-acceptance-report.json` records the latest Mac-side HTTPS/media result. Failed remote checks leave local chat running and report the problem. The report leaves the other-device browser test pending.

From another device, check:

1. Chat loads and previous folders/chats are visible.
2. A Small-model reply completes.
3. A new `/image` result displays and downloads.
4. A new `/video` link opens/downloads the generated MP4.

The Mac must be awake, connected to Tailscale and running Local AI. This addition does not configure unattended startup or wake-on-demand. A disconnected Tailscale client makes remote access unavailable; with remote configuration enabled, new media links also depend on it. Disable remote access and restart for purely local media links.

Old chat messages containing `http://127.0.0.1:8001/media/...` links are not rewritten. New results use the private media address. Normal text history and folders are shared across devices through the same database.

Authoring tests cover configuration, permissions checks, conflict handling, rollback, publisher rejection and the actual media-only HTTP handler. They do not execute a Mac package installation, a real tailnet, Safari or Windows. Native/private-network and browser checks remain necessary.

## References

- [Tailscale macOS installation](https://tailscale.com/docs/install/mac)
- [Official stable packages](https://pkgs.tailscale.com/stable/)
- [Tailscale Serve command](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [Tailscale signing team in its macOS deployment documentation](https://tailscale.com/docs/integrations/mdm/mac)
- [Open WebUI single-user mode](https://docs.openwebui.com/getting-started/quick-start/)
