# LOCAL AI installer: Captain launcher update

Extract this ZIP into a new folder. Run **Open Captain.command** on the Mac mini.
It uses the existing `~/LocalAI-Automated` installation. It starts an accepted
installation if stopped, checks the gateway, Captain agents, chat HTML and saved
sign-in, then opens Safari and displays the local login in Terminal.

If installation is incomplete, it reports the failed check and recovery action.
Run **Install LOCAL AI Core.command** from this folder to install the updated
modules and permanent launcher. Do not delete `~/LocalAI-Automated` or its models.
After successful installation, use `~/LocalAI-Automated/Open Captain.command`
for daily chat. Keep Terminal open until the launcher finishes its checks.

If Finder blocks the downloaded launcher, run this in Terminal after extracting
into Downloads (adjust the path if extracted elsewhere):

```bash
/bin/bash "$HOME/Downloads/mac-local-ai-installer/Open Captain.command"
```

The launcher never changes Gaming mode, kills a running supervisor, downloads
models, deletes data or marks an incomplete installation as accepted. It waits
up to three minutes for services, plus individual bounded probe timeouts. Repeated
clicks do not launch another supervisor. The loopback address works on the Mac
mini itself; another device needs separately configured remote access.

This update is based on the uploaded `Mac-Local-AI-Automated-Installer-2.zip`.
It does not contain the later additional-text-model separation discussed in chat.
An old document-model acceptance failure may therefore still block core setup;
this launcher reports it and does not bypass it. Existing full acceptance caching
is retained. Granular caching remains deferred until native acceptance succeeds.

HTTP checks verify the authentication challenge, saved credentials and HTML app
response. They do not establish successful Safari rendering or a human sign-in.
Native macOS launchctl, model inference, permissions and reboot checks must still
be completed on the target Mac. See VALIDATION.txt for this update's tests.

# Original installer instructions

Run `Install LOCAL AI Core.command` first. `Install Local AI.command` and the
older named MiniCPM launcher also default to core. Keep Terminal open while the
verified dependencies, Captain and small fallback install and run native tests.

For an unidentified-developer warning, open **System Settings > Privacy &
Security**, then **Open Anyway** for the core launcher. The scripts are unsigned;
see the [macOS approval steps](docs/MODULAR-INSTALLER.md#macos-blocks-a-downloaded-launcher).

Core needs native Apple Silicon, macOS 15+, 32 GB memory, Apple Command Line
Tools and 35 GB free storage. It installs no optional voice/media weights and
asks for no Discord token, reference WAV, vault, Docker licence, Proton key,
Tailscale login or GitHub credential.

Captain: `http://127.0.0.1:4096`, with local authentication. Ordinary chat:
`http://127.0.0.1:8081`. Worker delegation is in the Captain interface.
`Open Captain.command` displays its private login. User login startup is installed
after native core acceptance, not before FileVault unlock.

Run a named optional `.command` when that feature's inputs are ready. Each uses
the existing `~/LocalAI-Automated` installation and its pinned modules. Stop Local
AI and the Work Agent before installing; run `Start Local AI.command` afterward.
`Install Everything.command` runs the same modules, leaving unfinished work in
its own state. `Check LOCAL AI Setup.command` lists status and the exact next
installer. `Test Discord Voice.command` performs supervised call acceptance.

See [modular installation](docs/MODULAR-INSTALLER.md) for all launchers,
dependencies, recovery and remaining native checks. The Synod and studio source
is included, but institutional tools require accepted encrypted workspace storage
and the existing Village security checks. Core does not advertise them as usable.

Preserve existing models, chats, vaults and cached downloads during upgrades.
Run core over an interrupted installation to migrate it. A PR #40 trial backup
is restored without deleting it. No credentials or model weights are packaged.
The modular package remains a native Mac acceptance candidate. A package/source
hash match and source tests do not establish working Apple GPU inference,
permissions, physical audio or reboot behaviour.
