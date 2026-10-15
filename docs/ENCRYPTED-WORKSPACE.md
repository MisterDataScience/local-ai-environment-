# Encrypted iCloud workspace and GitHub

Decision: keep Open WebUI. Store AI working documents in a Cryptomator vault in
existing iCloud Drive storage. The vault has a separate password, no remembered
password, no Keychain storage and no automatic unlocking. Neither the installer
nor the model receives the vault password or recovery key.

## What this release implements

- The Captain installer installs Cryptomator 1.19.3 for Apple Silicon using
  the official DMG, a pinned SHA-256 and macOS signature/Gatekeeper checks.
  Existing apps and registered vaults are preserved.
- **Vault registration now happens inside the one Captain installation**.
  Cryptomator opens for one-time creation or unlock in its own GUI, where you
  select the vault password and save the recovery key. The installer detects
  the unlocked mounted volume, requires explicit confirmation before adopting
  it, creates Inbox/Projects/Outputs/Archive and verifies a real workspace
  write/read/delete operation before continuing. No separate post-install
  `Configure AI Workspace.command` step is needed.
- On subsequent upgrades the configured vault identity is retained; if locked,
  the installer opens Cryptomator and requires the same existing vault to be
  unlocked. It will never silently adopt a different mount or create unencrypted
  fallback storage.
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

## One-time setup inside the Captain installation

The installer handles the Cryptomator application installation and registration
itself. You no longer run another script after installing LOCAL AI.

1. Run `Install Local AI.command`. The installer opens Cryptomator during
   installation. If there is no registered vault, use Cryptomator's **Create New
   Vault** wizard, name the vault **AI Workspace**, and store its *encrypted*
   folder in your existing iCloud Drive. Make sure iCloud Drive is signed in
   and the storage is available offline.
2. Set a separate password **inside Cryptomator**, not in Terminal or AI chat,
   and save the recovery key privately. Keep password remembering and automatic
   unlocking disabled. macOS may require approving an encrypted-volume backend.
3. Unlock the new vault and choose **Reveal Drive**. Return to the installer's
   Terminal window and press Enter. If a verified mounted volume named
   **AI Workspace** is detected, confirm with `YES`; otherwise provide the
   unlocked volume root path and confirm it. Never select the encrypted iCloud
   folder, an arbitrary disk, or a plaintext directory.
4. The installer registers the mount and checks the actual vault marker,
   creates the required folders, writes and reads a randomly named test file,
   verifies its content/hash and removes it. Any failure stops the installer
   and preserves progress for rerunning rather than reporting success.

**After installation**, unlocking still happens manually in Cryptomator
after login and whenever the vault is locked. No password or recovery key is
saved by LOCAL AI. Backups and encrypted tools operate only while it is
unlocked, and never fall back to local plaintext folders. If the mount path
changes after reboot, the same vault must be safely re-registered; it is not
silently replaced. `Configure AI Workspace.command` remains available for
intentional re-registration or repair.

The mounted-volume check verifies a separately mounted volume and marker but
cannot cryptographically certify that the selected drive comes from
Cryptomator. Confirm it in the Cryptomator application. The real macOS/iCloud
volume lifecycle remains unverified until tested on the owner's Mac.

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

The Captain installer now **performs registration and smoke testing
during installation**, but you must complete Cryptomator's own GUI wizard,
unlock the volume and confirm its mount. It never asks for, remembers or
retrieves your password or recovery key.

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
