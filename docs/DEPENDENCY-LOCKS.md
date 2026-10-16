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
transitively hash-locked. Docker images are digest-recorded on the first
installation, but their initial tag resolution is not a release-wide lock.
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
