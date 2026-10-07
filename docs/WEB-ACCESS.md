# VPN-isolated web search, page reading and reverse image search

Implemented in the prototype on 2026-10-05. Unit/mock checks passed; the Docker stack, Proton tunnel, DNS isolation and live search have not been exercised on your Mac. This is not a verified anonymity or leak-proof claim.

## Included behaviour

Open WebUI sends your message to the existing gateway. `/search QUERY` calls SearXNG through a small retrieval API, collects up to five results and attempts to read the first two pages. `/read URL QUESTION` reads one page. Your selected local text model answers using the retrieved evidence. Sources are appended as clickable links; the model is instructed to use numbered citations. Check citation accuracy for important answers.

SearXNG and the reader share **Gluetun's network namespace**, with no second network attachment. Gluetun uses **Proton Free WireGuard**, its firewall and encrypted upstream DNS. Both clients use a mounted resolver configuration pointing to `127.0.0.1`, Gluetun's DNS server. No host-side page downloader or direct-internet retry exists in these gateway paths. Retrieval errors return visibly without asking Ollama to invent a web answer. Ordinary offline chat remains available.

For ordinary chat, the launcher registers an authenticated server-side OpenAPI connection, Local AI VPN retrieval. It exposes `vpn_search_web`, `vpn_read_page` and, when configured, `vpn_reverse_image`. Enable it in the chat's Integrations menu, or attach it to a model. Open WebUI owns selection, execution, approvals and continuation; the gateway no longer runs its own tool loop. Source URLs/text and truncation/read-error labels are returned as untrusted data; whether the model cites them correctly is model-dependent. Live WebUI integration remains unverified. Explicit `/search` and `/read` remain unchanged.

## First installation: exact order

1. Install **Docker Desktop for Apple Silicon** using [Docker's official Mac instructions](https://docs.docker.com/desktop/setup/install/mac-install/). It is free for personal use under Docker's published terms. This helper does not install Docker itself or create a Homebrew installation.
2. Open Docker Desktop and finish its one-time macOS approvals. Wait for the engine to run. Use a local Docker context, not SSH/TCP or a remote daemon. Enable Docker to start at login for easier daily use.
3. Begin with **2 GB VM memory and 2 CPUs** in Docker's resource settings. This is a starting budget to measure, not a tested guarantee. Container limits total 896 MiB; Linux VM and Docker overhead are additional. The earlier 0.5–1 GB total-infrastructure estimate is not established.
4. Sign in to your free Proton account and open [WireGuard configuration](https://account.proton.me/u/0/vpn/WireGuard). Generate a configuration for a **free server** and keep it on the Mac. Do not enable paid port-forwarding options. Its `PrivateKey` is sensitive: do not paste it in chat or GitHub.
5. Download the updated automated ZIP, then extract it into Downloads as `mac-local-ai-installer`.
6. Run in Terminal:

   ```bash
   /bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI with Web Access.command"
   ```

   To also include private access from your other devices:

   ```bash
   /bin/bash "$HOME/Downloads/mac-local-ai-installer/Install Local AI with Web Access.command" --remote-access
   ```

7. When asked locally, paste **only the `PrivateKey` value**. Terminal does not display it. The helper validates its format and stores it privately. It pulls the three official container images, records immutable image digests and creates the Compose stack. It selects free Proton servers without a fixed country filter. SearXNG/Python versions are selected at first setup and frozen by digest; reruns do not silently upgrade them.
8. The helper checks the authenticated reader health endpoint and records `web-acceptance-report.json`. Readiness means Gluetun reports healthy. It does **not** establish working search or validated tunnel-drop/DNS privacy. Those report fields remain `pending`.
9. In Local AI, test `/search Python official tutorial`, then `/read https://www.python.org/ What is this website?`. Check source links and actual retrieved content. Repeat with Small and Everyday text presets. Long pages are truncated to a bounded input budget, not fully indexed.

## Optional Yandex reverse image search

Reverse image search is opt-in and is never called automatically. It uses Yandex Search API only when the `vpn_reverse_image` tool is explicitly invoked. The tool accepts a relative image path inside the manually unlocked encrypted AI Workspace, for example `Inbox/photo.jpg`.

Before anything leaves the Mac, the gateway opens the selected file through the workspace's mount-checked, no-follow file boundary, decodes it locally, applies EXIF orientation, removes metadata, converts it to RGB JPEG and downsizes it to a bounded derivative. The original filename, workspace path and EXIF metadata are not included in the Yandex request. Yandex still receives the derivative's image pixels, so this is not appropriate for an image you are unwilling to disclose to Yandex in any visual form.

The Yandex request does not use the Mac's ordinary HTTP client route. Gluetun exposes its HTTP proxy only on `127.0.0.1:8888`; the reverse-image client has environment-proxy inheritance disabled and explicitly assigns that proxy for both HTTP and HTTPS. It first checks the existing authenticated VPN health service. Redirects are disabled. If the VPN health check fails, the proxy is missing, the proxy request fails or the response is invalid, the operation stops. There is no direct-internet retry.

### One-time setup

1. Configure the encrypted AI Workspace and VPN web access first.
2. In Yandex Cloud, create or select a folder and a service account permitted to use Search API. Give it only the Search API role required for this feature and create an API key with the Search API execution scope.
3. Stop Local AI.
4. Run:

   ```bash
   /bin/bash "$HOME/LocalAI-Automated/Configure Reverse Image Search.command"
   ```

5. Enter the Yandex Cloud folder ID and paste the API key into the hidden prompt. They are stored locally in `control/config.json`, which is mode 0600. Do not commit or publish that installed runtime directory.
6. Restart Local AI. Enable the Local AI VPN retrieval integration in Open WebUI if it is not already enabled.
7. Put the image to search in the encrypted workspace, then request a reverse-image search. The model can call `vpn_reverse_image` with a path such as `Inbox/photo.jpg`.

To disable the feature while Local AI is stopped:

```bash
/bin/bash "$HOME/LocalAI-Automated/Disable Reverse Image Search.command"
```

Returned matches include Yandex's image/page URLs and bounded descriptive metadata. A visual match is evidence of similarity, not proof that a page is the original source, that two depicted people or objects are identical, or that a particular uploader owns the image. Use the existing VPN page-reading tool to inspect promising public source pages separately.

## Existing installation

Stop Local AI with Control+C and wait for shutdown. Run the updated normal installer once to copy the new gateway/helper files. It preserves chats, secrets, edited text presets and workflows. Downloads are reused; the changed gateway invalidates the previous acceptance fingerprint and may rerun native generation checks.

Complete Docker/Proton steps 1–4 above, then run:

```bash
/bin/bash "$HOME/LocalAI-Automated/Enable Web Access.command"
```

Once configured, the existing Local AI launcher starts the stack automatically. If Docker/VPN is unavailable, it warns and starts local chat. Web requests fail without an alternate route. Web containers may remain running after closing Local AI; they load no AI model weights. Automatic AI startup at login remains unfinished.

While Local AI is stopped, disable web access with:

```bash
/bin/bash "$HOME/LocalAI-Automated/Disable Web Access.command"
```

This removes only this installation's Compose containers/network, preserving config/credentials for reuse. It leaves Tailscale, other Docker projects, images, Docker Desktop and Mac network settings alone. Restart Local AI afterward.

## Usage and limits

| Chat input | Behaviour |
| --- | --- |
| `/search What changed in Python 3.14?` | Search, attempt two result pages, answer locally with sources |
| `/read https://docs.python.org/3/whatsnew/3.14.html Summarise the changes.` | Read that HTML page and answer the question |
| `/read https://www.python.org/` | Summarise the page |
| Ordinary research/page-reading request | Enable Local AI VPN retrieval in the chat; model can call its tools, with selection and citations requiring validation |

PDFs, authenticated sites, paywalls, JavaScript-only pages, transcripts, recursive crawling and clicking buttons are unsupported. Sites can refuse VPN IPs or this reader. Engines can rate-limit SearXNG. Failed page reads are labelled; snippets are not labelled full pages. Citation correctness is model-dependent.

## Security boundaries

- Public HTTP/HTTPS URLs on ports 80/443 only. URL credentials and local/private/reserved/multicast addresses are rejected, including mixed public/private DNS. Connections are pinned to a validated IP, with certificate verification and original-hostname TLS. Redirects are revalidated; HTTPS downgrades blocked.
- Redirect, byte, text, time and concurrency limits bound work. Scripts/styles are stripped; no JavaScript executes. Retrieved instructions are untrusted evidence. Prompt-injection mitigation is not a model-behaviour guarantee.
- Only the authenticated reader endpoint and the Gluetun HTTP proxy are published, on **127.0.0.1:8090** and **127.0.0.1:8888** respectively. Both bind to loopback. SearXNG and VPN health are not separately published. The reader is unprivileged/read-only, with no Docker socket or chat/model files mounted. Do not expose 8090 through LAN/Tailscale/Funnel.
- The gateway contacts only the fixed loopback endpoint. Remote-device retrieval happens on the Mac. Clicking a source yourself uses normal browser/device traffic, not AI retrieval.
- Proton sees your VPN connection; sites see its exit IP. Upstream search engines receive the search query. The reader sends the requested URL, not chat history. Your local model receives fetched text. This is not absolute anonymity.
- Open WebUI built-in search is disabled. `ENABLE_LOCAL_WEB_FETCH=False` blocks private-network destinations for its loader, **not all public URL loading**. Do not use separate website/URL ingestion or third-party tools/plugins/previews as substitutes for the VPN OpenAPI bridge or explicit commands. This version does not impose OS-level outbound blocking on native processes. Isolation claims cover the implemented gateway paths, not every possible WebUI extension or feature.
- Software/model/container downloads use ordinary internet. Gluetun contacts Proton to establish the tunnel. Neither is an AI-search fallback. No whole-Mac VPN, exit node, router forwarding or subnet route is configured.
- Credentials stay in `~/LocalAI-Automated/web/vpn.env` and `reader.env` (0600, parent 0700). A Mac administrator or someone controlling Docker can inspect container environment values. Config backups contain secrets too. Never publish the installed runtime directory.

## Native validation still required

1. Inspect Compose: both clients share `service:vpn`, only VPN publishes loopback 8090 and 8888, no outbound-subnet bypass, both resolver files point to Gluetun DNS. Confirm the HTTP proxy is enabled and bound only to loopback.
2. Establish successful searches/reads. Compare the reader container's observed public IP against the Mac/browser's ordinary IP. They should differ. Test inside the reader, not on the host.
3. Interrupt WireGuard **while keeping the reader alive**. `compose down` is not a kill-switch test. Check both the API and a direct public-IP connection inside the reader namespace to verify firewall blocking. Gluetun auto-heals: capture the failed interval or temporarily disable healing in a controlled test. Pausing Gluetun alone may leave kernel WireGuard active.
4. Observe DNS traffic during successful queries and interruption. No AI-query DNS should leave on the ordinary container interface or via Docker/host resolvers. VPN transport on that interface is expected.
5. Restart Docker/the stack and repeat. Confirm clients share the new VPN namespace and no fallback network appears. Restore healing after testing.
6. Record the results. No automated packet-capture/tunnel-cut harness is included yet. Structural checks/mocks do not replace these pending tests.

## Primary references

- [Gluetun Proton and FREE_ONLY](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/protonvpn.md)
- [Gluetun shared network](https://github.com/qdm12/gluetun-wiki/blob/main/setup/connect-a-container-to-gluetun.md)
- [Gluetun DNS](https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/dns.md)
- [Gluetun firewall](https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/firewall.md)
- [Gluetun HTTP proxy](https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/http-proxy.md)
- [Yandex Search API image search](https://yandex.cloud/en/docs/search-api/api-ref/ImageSearch/searchByImage)
- [SearXNG JSON API](https://docs.searxng.org/dev/search_api.html)
- [SearXNG Docker](https://docs.searxng.org/admin/installation-docker.html)
- [Proton WireGuard configurations](https://protonvpn.com/support/wireguard-configurations/)
