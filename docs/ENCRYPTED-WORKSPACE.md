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

## Media, backups and existing files

With the vault registered and unlocked, use `/image DESCRIPTION` or `/video
DESCRIPTION` in Open WebUI. The bundled ComfyUI output nodes save PNGs and MP4s
straight into `Outputs/Media` through checked file descriptors. Video frames
stream through FFmpeg in memory; no plaintext conversion-frame directory is
created. Vault mode accepts only the bundled node types, disables other custom
nodes, previews and image metadata, and suppresses ComfyUI's plaintext log.
The gateway still unloads Ollama before rendering and stops ComfyUI afterwards.

The media listener reads from the mounted vault, supports video byte ranges, and
sends `Cache-Control: no-store`. The configured private Tailscale media address
works from other devices while the Mac and vault are available. Locking the
vault prevents subsequent access; an in-flight chunk or a file already downloaded
to another device cannot be recalled. Generated UUID links use the existing
loopback/private-tailnet access boundary, not an additional login per file.

Open WebUI's **live database, uploads, indexes and application logs stay local**.
Do not put the active SQLite database in iCloud. Enable macOS FileVault separately;
the installer does not configure or verify it. Tool results can enter chat history,
and chat uploads are not redirected into the vault. This is encrypted working
files and backup storage, not a claim that all AI data exists only in the vault.
Models and dependencies also remain on the local SSD.

While the vault is unlocked, the launcher takes an offline WebUI-data backup before
startup and after clean shutdown. It includes SQLite WAL files, uploads and
indexes, and the stable WebUI secret needed to restore OAuth records. Rebuildable
`webui/data/cache` is excluded, so model/cache files may download again on restore.
Backups therefore contain sensitive account/chat data and stay inside the vault.
The separately stored GitHub PAT and vault password are not included.
If the vault is locked, chat can still start; a warning reports the missed backup.
A crash/power loss cannot produce a shutdown backup. The next unlocked startup
backs up the surviving local data before opening WebUI.

Three helpers are installed beside `Start Local AI.command`:

- **Back Up AI Workspace.command:** stop Local AI, unlock the vault, then run it.
  Archives go into `Archive/Backups`. Only the newest three generated UUID-named
  backups are retained. This directory is reserved for these rotating backups.
- **Restore AI Workspace.command:** stop Local AI, unlock the vault, then paste
  the relative archive path, e.g. `Archive/Backups/UUID.zip`. The helper validates
  paths and checksums, restores to a new local directory, restores the WebUI
  encryption secret, and preserves previous data as `webui/data.before-restore-*`.
  GitHub tokens and account connections still require their normal credentials.
- **Archive Existing AI Files.command:** stop Local AI and unlock first. It writes
  an archive under `Archive/Migration` containing WebUI data, old gateway media,
  ComfyUI output/temp files and logs. It also copies recognized generated UUID
  media into `Outputs/Media`, preserving existing media URLs. Existing vault files
  are never overwritten. Other legacy filenames remain available in the archive.
  Original local files are preserved; this does not erase plaintext copies or
  promise secure deletion on an SSD. Migration archives are not rotated.

Do not edit the local data directories with another program during backup or
restore. Helpers refuse known active services and cooperative runtime locks.
Archives are ordinary ZIPs *inside the encrypted mounted vault*. Exporting one
outside it exports plaintext, including any contained account records.

## Boundaries

There is no automatic vault unlock, login launch agent or password prompt in chat.
You unlock once in Cryptomator after login as needed. GitHub is separate storage:
committing a vault file creates a plaintext repository copy under GitHub's access
permissions. Account traffic uses the ordinary connection; web retrieval keeps
its VPN route. File-tool restrictions do not sandbox arbitrary Python plugins,
code interpreters, direct OS access or other integrations.

The installer can install software and register an unlocked vault, but you must
create/unlock it in Cryptomator and select its mounted root. It never asks for,
remembers or retrieves your password or recovery key.

## Verification on the Mac

Authoring tests cover descriptor-based writes, lock failure cleanup, output
symlinks, real FFmpeg pipe encoding, loopback media range requests, engine handoff,
backup/restore of SQLite with WAL, archive checksums, backup retention and migration.
Mount state is simulated in these tests. This is not native Cryptomator, iCloud,
Apple GPU, live Open WebUI or account acceptance evidence.

1. Unlock the configured vault and start Local AI. Generate an image and short
   video. Confirm files appear in `Outputs/Media`, not local ComfyUI output/temp
   or gateway media folders. Check playback and download on the Mac and phone.
2. Lock the vault. Try new file operations, generation and an existing media URL;
   all must fail without creating an ordinary fallback directory. If open files
   prevent locking, allow the operation to finish; avoid forced unmount for testing.
3. Unlock, make a sample chat/upload and shut down cleanly. Check the backup path
   printed in Terminal. Run the restore helper with that archive; restart and
   verify the sample chat/upload. Previous data remains available for recovery.
4. Verify iCloud finishes syncing; open the synced vault on another device and
   check a sample output. Avoid simultaneous edits across devices.
5. Verify Open WebUI approval denial/reload and GitHub calls using a disposable
   repository before granting access to important repositories.

## Upstream references

- https://github.com/cryptomator/cryptomator/releases/tag/1.19.3
- https://docs.cryptomator.org/desktop/password-and-recovery-key/
- https://docs.cryptomator.org/desktop/volume-type/
- https://docs.openwebui.com/features/extensibility/mcp/
- https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md
- https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md
