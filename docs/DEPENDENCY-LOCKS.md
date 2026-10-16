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

Other environments, including Open WebUI and auxiliary tools, retain direct
version pins and the release cutoff where uv is used. They are not all
transitively hash-locked. Docker container selection is release-locked as described below.
Do not describe the entire installer as bit-for-bit reproducible.

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
