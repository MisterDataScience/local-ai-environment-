# Next additions

Recorded 2026-10-06 at the user's request. Include this note in the next GitHub update.

## Agreed follow-up: native Open WebUI code execution

Evaluate and enable the code-execution functionality already supplied by our pinned
Open WebUI version instead of building a duplicate executor. Check the configured
engine, where execution occurs, supported libraries/files, network access,
credential isolation, vault output handling and compatibility with resource modes.
Verify actual execution and result return through our model/gateway configuration.
Update: the pinned Open WebUI v0.11.1 source already defaults both code execution
and interpreter to enabled with Pyodide. The OpenCode integration commit makes
these settings explicit. Native browser execution and result-return checks remain
pending; this is configuration, not evidence of a successful Mac run.

## Proposal only: an AI-operated browser

Investigate Microsoft's Playwright MCP as a separate browser-control capability
attached to the existing Open WebUI tool loop. Prefer structured page snapshots to
adding a vision model. Scope an isolated AI browser with visible progress, bounded
runs and human takeover. Public browsing should preserve the project's VPN-only,
fail-closed requirement. Logged-in accounts need separate explicit authorization.
Do not treat native experimental tool approval as a complete action-security gate.
No browser integration or new autonomous permissions authorized yet. Measure local
model reliability before promising unattended completion. Do not build a second
agent loop when the existing UI can drive the tools.
