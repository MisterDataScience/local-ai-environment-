# GitHub integration: supported host path, not yet configured

The bespoke disabled GitHub MCP adapter and its proposal/approval lifecycle have
been removed. No local AI account access, credential provider, repository write
connection or separate approval website is active.

The intended integration is GitHub's official MCP server connected through Open
WebUI's supported tool interfaces. Open WebUI should own the tool loop, in-chat
approval and result continuation. A narrowly scoped policy bridge may still be
needed for requirements the host/token cannot enforce. It is not implemented.

Do not attach an unrestricted GitHub token merely because the UI has an approval
toggle. Before enabling writes: select a supported tested WebUI release, check
native Allow/Deny and restart behavior, constrain account permissions, verify
which chat contexts bypass approval, and exercise a disposable repository.
Confirm file SHA conflicts and uncertain-write outcomes using the official server.

Keychain storage and account activation have not been implemented. Secrets must
remain outside prompts and model-visible tool arguments. GitHub traffic may use
the normal connection, as requested; it need not use the VPN search service.

See [native tools and the revised boundary](NATIVE-TOOLS.md). Historical adapter
code remains recoverable from commit bb8cf01c4a387857393b6a72178344a258658da0.
