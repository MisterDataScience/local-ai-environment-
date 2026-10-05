# Private tool loop retired

The gateway-owned model/tool/model loop was removed after checking Open WebUI's
native tooling. The current implementation uses Open WebUI's tool loop and
approval UI, with the gateway limited to model lifecycle work and protocol
translation. See [NATIVE-TOOLS.md](NATIVE-TOOLS.md).

The earlier calculator/time workers, private registry and disabled GitHub
proposal/approval adapter are no longer shipped. Git history retains them.
Explicit VPN web commands remain; ordinary web tools use a small supported
OpenAPI bridge. No GitHub or Dropbox account is connected.

This file remains as a redirect for earlier documentation links.
