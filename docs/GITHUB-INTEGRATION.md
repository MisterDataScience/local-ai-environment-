# GitHub adapter: implemented, account activation pending

The installer includes a restricted GitHub adapter and a tool-loop integration point.
It does **not** connect your account. There is no credential prompt, Keychain integration,
approval screen or supported activation command yet. Setting `github.enabled` in the
runtime config is rejected. No credentials are required for the tests.

This is a read/write design, not a permanent read-only restriction. This first stage
supports reading existing text files and proposing a single-file replacement commit.
New files, directory browsing, repository search, issues, pull requests, bulk commits,
deletion and Dropbox remain unimplemented.

## Existing software versus custom code

GitHub provides the official MCP server and its `get_file_contents` and
`create_or_update_file` tools. The optional transport uses the official Python MCP
SDK's supported v1 API (`mcp>=1.28,<2`). It targets GitHub's hosted MCP endpoint,
`https://api.githubcopilot.com/mcp/`, avoiding another local Docker service. The SDK
dependency is deliberately not installed while account access is disabled.

The repository/branch policy, proposal storage, exact approval binding and tool-loop
adapter are our custom code. Hosted MCP availability for your account/token, SDK
interoperability and real file-result shapes have not been exercised here. The live
service may change independently of the installer. An unexpected result fails closed.

GitHub traffic would use the ordinary connection, as requested. AI inference stays
local, but GitHub receives the API requests and any content submitted in a commit.
No GitHub operation is routed through the VPN search service.

## Implemented operation order

1. Trusted host code constructs the adapter with exact repositories and branches.
   The current installer never does this. Chat cannot select a server URL, supply a
   token, activate an account or expand the policy.
2. The model can request `github_read_file` or `github_propose_file_change`.
   The adapter validates all arguments before network activity.
3. The official MCP read tool returns the text and current blob SHA from the requested
   branch. The adapter accepts only the expected text-resource shape and exact
   repository/path. It rejects fallback notices, symlink notices, binary files,
   resource links and directory responses. It never follows a download URL.
4. Reads return at most 2,500 UTF-8 bytes to the model and label truncation. Proposals
   contain full replacement text, up to 4,096 bytes, and a commit message up to 200 bytes.
5. A proposal binds repository, branch, path, replacement content, message and base
   file SHA to a SHA-256 digest. It expires after ten minutes; restart loses it.
   At most 32 proposals remain pending. Nothing is committed at this stage.
6. A future trusted approval UI must display the exact proposal through `review()`.
   Only that controller may call `approve_and_commit()` with the reviewed digest.
   Approval is deliberately absent from the model's tools. Saying “approved” inside
   a model response or retrieved document cannot call this method.
7. The adapter consumes approval, rechecks policy and reads the current file again.
   If its SHA changed, a new proposal and review are required.
8. It calls the official write tool with plain text and the approved base SHA. That
   SHA protects against a competing update between the check and final write.
   This checks the file, not the entire branch head; unrelated file commits may occur.
9. A timeout or failed write consumes the proposal and is not retried by this code.
   The remote write may have succeeded before a timeout. Check GitHub before preparing
   another proposal. Exactly-once network delivery is not promised.

## Credential and prompt-injection boundaries

The transport accepts a credential-provider callable supplied by trusted host code.
The planned provider will use macOS Keychain; that provider is **not implemented**.
Do not put tokens in config, prompts, chat history or repository files. Later setup
must use an expiring fine-grained token scoped to selected repositories and only
necessary permissions. A tool allowlist does not reduce the token's underlying rights.

Credentials would be placed in the transport's authorization header. Remote
exceptions are replaced with a generic error before entering model messages.
Repository content remains untrusted and could contain secrets of its own; this
does not automatically scrub sensitive files or make prompt injection harmless.

When a trusted host injects an enabled GitHub adapter into the tool loop, public
web search/page tools are both hidden and blocked for that request. This reduces
one direct exfiltration route. It does not protect subsequent requests that reuse
private chat history, native WebUI plugins, compromised host processes or other
uncontrolled network clients. Neither the adapter nor its SDK is an OS sandbox.

## Validation and remaining work

Simulated official MCP responses test allowed repositories/branches, strict paths,
bounded reads, proposals without writes, exact and single-use approvals, expiration,
stale SHA rejection, policy rechecks, secret-safe errors, uncertain writes and
tool-loop integration. Existing installer and gateway tests also pass.

Before activation: implement and test Keychain storage/retrieval; build an approval
screen independent of model output; restrict account permissions; exercise official
MCP interoperability using a disposable repository; verify a read, an approved write,
a denied write, a competing edit and a timeout; then run native Mac acceptance.
The current adapter tests do not establish live account safety or Mac compatibility.

Primary references checked 2026-10-05:

- [Official GitHub MCP server configuration](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)
- [Official read/write tool implementations](https://github.com/github/github-mcp-server/blob/main/pkg/github/repositories.go)
- [Official resource URI templates](https://github.com/github/github-mcp-server/blob/main/pkg/github/repository_resource.go)
- [Supported Python MCP SDK v1 documentation](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
