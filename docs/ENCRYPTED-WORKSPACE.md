# Encrypted iCloud workspace and GitHub

Decision: keep Open WebUI. Store AI working documents in a Cryptomator vault in
existing iCloud Drive storage. The vault has a separate password, no remembered
password, no Keychain storage and no automatic unlocking. Neither the installer
nor the model receives the vault password or recovery key.

## What this release implements

- The normal installer installs Cryptomator 1.19.3 for Apple Silicon using the
  official DMG, a pinned SHA-256 and macOS signature/Gatekeeper checks. An existing
  installation is verified and preserved, not overwritten.
- `Configure AI Workspace.command` opens Cryptomator and registers an already
  unlocked volume. It creates Inbox, Projects, Outputs and Archive directories.
- Four OpenAPI tools: list a folder, read UTF-8 text, create/revise UTF-8 text,
  and create a subfolder. A file is limited to 256 KiB. No delete, shell,
  arbitrary binary upload, recursive search or outside-folder access is exposed.
- Every request requires the correct mounted volume and vault identity marker.
  Operations use directory file descriptors with no-follow opens. Parent paths,
  symlinks, special files and hard-linked input files are rejected. A missing
  mount is never created as an ordinary fallback folder. Revision hashes reduce
  accidental overwrites; edits by unrelated apps are not transactional with us.
- GitHub uses its official remote MCP service. No private GitHub agent loop is
  reintroduced. Setup registers a limited tool selection for repositories,
  branches, files, issues and pull requests. The token's GitHub permissions are
  the actual account boundary; tool selection alone is not one.

The workspace API is a small custom storage boundary, not the generic filesystem
MCP/mcpo pair originally proposed. A generic allowed directory does not establish
that the expected encrypted volume is still mounted. This boundary checks that
condition per request and avoids giving a long-running generic file server a
fallback directory. Open WebUI still owns all model tool loops and approvals.

## One-time setup on the Mac

1. Run the normal Local AI installer. Hardware tests initially use synthetic
   sample prompts, outside the vault, before a workspace is registered.
2. Stop Local AI with Control+C in its Terminal.
3. Run `~/LocalAI-Automated/Configure AI Workspace.command`.
4. In Cryptomator create **AI Workspace** inside your iCloud Drive. Use a unique
   password. Leave **Remember password** and automatic unlocking disabled.
   Write the recovery key down and keep it separately. Do not paste either
   secret into the installer, GitHub or AI chat.
5. In Finder, keep the encrypted iCloud vault folder downloaded on this Mac.
   Cloud sync, quota and local availability still require iCloud to be signed in.
6. Unlock the vault. Use a Cryptomator volume backend that mounts a separate
   filesystem; follow Cryptomator's macOS prompts for any required components.
   Directory-only/no-mount arrangements are deliberately rejected.
7. Click Reveal Drive and provide the ROOT path of that unlocked volume to the
   helper. Do not provide the encrypted iCloud folder or a subfolder. The helper
   checks mount identity, but does not independently prove that your chosen
   mounted filesystem is Cryptomator. Select it carefully in this one-time step.
8. Restart Local AI. In a saved Open WebUI chat, enable **Encrypted AI Workspace**
   under Integrations and select **Ask for approval**. Existing chat/model
   settings may override installer defaults; verify the setting explicitly.
9. Ask it to create `Outputs/check.md`, read it, then edit it. Deny a proposed edit
   and verify the file is unchanged. Lock the vault and verify file tools fail.
10. After a restart, unlock the same vault at the same mount path. If macOS
    changes the path (for example by adding a suffix), stop Local AI and rerun
    the configuration helper. Do not create replacement directories manually.

The vault is created once. Unlocking makes its decrypted contents available to
permitted processes on that Mac. Access through Open WebUI on another device
requires the Mac to be running with its vault unlocked. To browse the files
independently on another device, install Cryptomator there and unlock its synced
copy. Let iCloud finish syncing and avoid concurrent edits to the same file.

## GitHub setup

Run `~/LocalAI-Automated/Connect GitHub.command` while Local AI is stopped.
Create a fine-grained personal access token for selected repositories only. For
writes, enable Contents, Issues and Pull requests read/write, with an expiry.
Paste it into the helper's hidden input. It goes to a mode-0600 file in the local
mode-0700 `secrets` directory, outside iCloud and outside the vault. This is an
API credential, not the vault password. It is not stored in Keychain.

Open WebUI receives the credential through its server configuration/environment;
privileged processes and its administrator can access it. It is not a tool
argument or model message. No credential is included in this repository or ZIP.
The connection is registered, not automatically attached to every conversation.
Enable GitHub in chat Integrations after restart. GitHub authentication, token
expiry, permission and approval behavior still require live tests on the Mac.
Use a disposable repository: read, deny a proposed write, approve a write, then
reload the chat and verify the resulting commit. Stop if denial still executes.
Open WebUI 0.11.1 approvals are experimental, not a separate backend security
boundary. No claim is made here that their reported edge cases are resolved.

## Explicit storage boundaries and remaining work

**This release does not claim that all AI data is stored in the vault.**

- Open WebUI chat history, attachments, extracted text/indexes, logs and its live
  database remain in `~/LocalAI-Automated/webui/data` and other local runtime
  folders. File tools may return private content into chat history. Do not use
  sensitive content until you accept this separate boundary. Enable FileVault
  separately on the Mac; the installer does not configure or verify it.
- Image/video generation AND legacy media downloads are blocked while vault mode
  is enabled. ComfyUI outputs, conversion frames and temporary files still need
  dedicated migration and native verification. The old media is preserved on
  disk; it is neither moved nor erased. Vault-disabled legacy installations keep
  their existing media behavior. Do not disable vault mode for sensitive media.
- A consistent database-backup command into the vault is still pending. Never
  relocate the live Open WebUI SQLite database into an actively synced folder.
- There is no automatic vault unlock, login launch agent, password prompt in the
  chat, binary file download link, or migration/deletion of existing data.
- GitHub is separate storage: committing a vault file creates a plaintext copy
  in that repository according to GitHub's access permissions. Account traffic
  uses the ordinary connection, as requested; web retrieval keeps its VPN route.
- Restricting these file tools does not sandbox arbitrary Python plugins, code
  interpreters, direct OS access or other integrations. Do not add those and
  assume the same vault-only boundary applies to them.
- Models and application dependencies remain on the local SSD, not inside iCloud.

## Verification

Authoring tests exercise real temporary files and loopback HTTP, with mount state
simulated where necessary. They cover authentication, locked/missing/wrong volume,
path traversal, symlinks, special files, revision checks, text limits, token file
permissions, multi-connection configuration and media blocking. These are not
native Cryptomator, iCloud, Apple GPU or live-account acceptance results.
The Mac must verify mounting/unmounting, file operations with its chosen backend,
sync to Windows/iPad, Open WebUI approval denial/reload, and GitHub calls.

## Upstream references

- https://github.com/cryptomator/cryptomator/releases/tag/1.19.3
- https://docs.cryptomator.org/desktop/password-and-recovery-key/
- https://docs.cryptomator.org/desktop/volume-type/
- https://docs.openwebui.com/features/extensibility/mcp/
- https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md
- https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md
