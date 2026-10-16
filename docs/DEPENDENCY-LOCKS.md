# Dependency lock scope and maintenance

The Captain installer uses `installer/locks/comfy-macos-arm64-py312.txt`
for ComfyUI, including Torch, TorchVision and TorchAudio. It pins all 85
resolved packages and their SHA-256 artifact hashes for CPython 3.12 on
macOS 15 or later, Apple Silicon. Installation requires wheels and matching
hashes; it never compiles an unexpected source distribution.

The lock was generated using uv 0.12.20 and a package publication cutoff of
2026-10-16T11:00:00Z. Cross-platform resolution and a hash-enforcing dry run
passed on Linux. This establishes a resolvable wheel plan, not native imports
or Metal/MPS execution. Those still require the Mac. The installer checks
the exact Torch trio and available MPS before writing its dependency receipt.
Changing the lock hash invalidates an old dependency checkpoint.

The input reflects `requirements.txt` from ComfyUI commit
`6b747c0428c343e1417219641db93a4fb7cb69ae`, with the tested Torch trio pinned.
To regenerate deliberately, use the pinned uv version from the repository
root:

```bash
MACOSX_DEPLOYMENT_TARGET=15.0 uv pip compile \
  installer/locks/comfy-macos-arm64-py312.in \
  --python-version 3.12 --python-platform aarch64-apple-darwin \
  --only-binary :all: --exclude-newer 2026-10-16T11:00:00Z \
  --generate-hashes --output-file installer/locks/comfy-macos-arm64-py312.txt
```

Review the diff, confirm upstream requirements have not changed, run a dry
run with `--require-hashes` on that platform, then validate on native macOS.
The macOS deployment target matters: uv's default target is older than this
installer supports and rejects some compatible wheels.

Existing ComfyUI source is compared against the SHA-verified pinned archive
before dependencies are installed. Missing source files are repaired in place.
Modified upstream files or source symlinks stop installation without being
overwritten or falsely marked as the pinned revision. Extra models, workflows,
outputs and custom nodes remain intact. A deliberate future source-version
upgrade needs a migration policy for modified upstream files.

# Remaining Python environments

All Python package-install paths in the Captain installer now consume exact,
artifact-hashed locks. The locks target macOS 15+ ARM64 and the environment's
Python minor version:

| Environment | Lock | Packages |
| --- | --- | ---: |
| Control/gateway and private CMake | `control-macos-arm64-py311.txt` | 8 |
| Open WebUI | `webui-macos-arm64-py311.txt` | 263 |
| Shared speech/transcription | `voice-macos-arm64-py312.txt` | 66 |
| Speech build backend | `voice-build-macos-arm64-py312.txt` | 2, also included in the voice lock |

`dependency_locks.py` checks the native OS, architecture and Python minor
before package changes. It uses `uv pip sync --require-hashes` on these
application-owned virtual environments, followed by `uv pip check`. Repeat
installation reconciles versions and removes unlisted packages even when an
old checkpoint exists. User files, models and WebUI data live outside those
virtual environments. Hand-installed Python extensions inside them are not
preserved. Daily startup does not install or update Python packages.

Control and WebUI are wheel-only. The only source-build exception is MLX Audio
at existing commit `200aac3c64e5140dbe0daa4570dcb129f0f7afc9` (version 0.5.8).
Its archive SHA-256 is
`92a1075616ecc5fefff6ac07280565b28d52162644e7a75ebd99d2a696ac64e9`.
The installer first installs hash-checked setuptools 80.9.0 and wheel 0.45.1,
then builds without isolation, so build dependencies cannot float. All other
voice packages require wheels. TTS and conversation use the same complete
lock, preventing successive installs from resolving different shared versions.
Both model receipts include runtime and build lock hashes, invalidating old
load checks after a lock change. Deployed locks also enter the installer's
native acceptance fingerprint. Failed dependency/load checks stop installation.

The old CMake fallback requested `cmake==3.31.8`, which is absent from PyPI.
The control lock now selects the available 3.31.10 universal2 wheel. Captain
uses that private CMake regardless of a different version on the Mac's PATH.

The new locks were generated with uv 0.12.20 and cutoff
2026-10-16T11:00:00Z. To regenerate control/WebUI, use the ComfyUI command
pattern with the corresponding `.in`/`.txt` paths and `--python-version 3.11`.
For voice use Python 3.12 and add `--no-binary mlx-audio` to the compile
command. The separate build lock uses the wheel-only command. Review changes
as a managed release, preserving compatible MLX source, model revisions,
backend versions and the complete dependency closure.

Local evidence for this change:

- Hash-enforcing recursive install plans resolved for all three environments,
  targeting their exact macOS platform and Python minor version.
- All eight actual control wheels were downloaded and SHA-256 verified into a
  staging directory. Mac binaries were not executed.
- The actual pinned MLX archive built successfully on Linux using only the two
  locked build tools, without isolated dependency resolution. This validates
  packaging, not MLX imports, Metal or speech inference.
- A real uv installation removed an unlisted test package. A deliberately
  changed wheel then failed its SHA-256 check, preserving the previously
  installed package.
- Eight new regressions cover lock completeness, install ordering, repeat
  reconciliation, deployed locks, acceptance invalidation, platform refusal
  and failed-install receipts. The installer suite passed 287 tests with four
  Apple-only skips (291 discovered).

WebUI/voice Mac wheels have resolvable plans; their complete artifact downloads
and native imports have not been exercised here. Clean/repeat installation,
WebUI startup and all three voice worker checks still require the physical Mac.
Python interpreter patch releases, native OS frameworks and locally built
output bytes are outside the package locks. Do not describe the entire
installer as bit-for-bit reproducible. Docker container selection is
release-locked as described below.

# Hosted CI budget

The required-features workflow is manual-only while the hosted allowance is
exhausted. Ordinary PR updates and documentation commits do not start it.
No workflow was dispatched during this recovery. A deliberate dispatch runs
Linux checks; native macOS jobs require the `native_macos` input. Publishing
also requires `publish_installer`, main, and all three successful gates.
Skipped native checks cannot authorize publishing.

The recovery commit includes `[skip ci]` so the PR's previous automatic
workflow cannot start while that commit changes its triggers. No release ZIP
is published until native verification is restored.

# Managed container releases

`installer/web_access.py` specifies immutable publisher manifest-index digests
for Gluetun v3.41.0, SearXNG 2026.10.16-0ce72dd2c, the selected Python 3.12
Alpine image and Microsoft's Playwright MCP image. No mutable tag is used to
pull them. Registry evidence is in `CONTAINER-IMAGE-LOCK.json`, recorded on
2026-10-16. Each index, its ARM64 child manifest and that child's configuration
were fetched over HTTPS and independently SHA-256 checked. The configuration
confirms Linux/ARM64. This verifies artifact identity and platform, not execution.

Both pull commands and Compose explicitly select `linux/arm64`. After pulling,
the installer checks the exact repository digest and OS/architecture before
writing image receipts or launching the new Compose definition. It does not
accept an arbitrary first `RepoDigests` entry. Missing images are pulled again
by digest on reinstallation. A failed pull leaves the previous image receipt
and Compose definition intact.

`web/images.json` is an installed receipt, not an update channel. Rerunning the
single installer replaces older image selections with this release's pins,
including the browser when already enabled. Standalone browser configuration
requires matching web-stack pins and installs the same pinned browser.
Profiles, outputs and credentials are retained. Daily startup uses `--pull
never`; it never follows a changing upstream tag. There is no automatic image
upgrade service. Future changes require the owner's deliberate installer update.

To update deliberately, resolve the desired publisher tag, hash the exact
manifest-index response, verify its Linux/ARM64 child and configuration hashes,
and change the constants and evidence together. Run installer and browser
regressions, then validate actual VPN/search/reader/MCP behavior and the VPN
kill switch on the Mac before deploying that release. Digest pins do not
establish the absence of vulnerabilities or supply-chain compromise.

Local validation for this change: 279 installer tests passed, four Apple-only
tests skipped (283 discovered); compilation and installer archive checks passed.
Docker Engine and the Mac are unavailable on the authoring host, so real image
pull/inspection, container startup and integration acceptance remain pending.
