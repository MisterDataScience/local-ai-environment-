"""No floating bootstrap/toolchain dependencies can enter first-install critical path."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'payload')]
import installer
import docker_setup


class InstallerPinTests(unittest.TestCase):
    def test_versioned_and_checksums_native_bootstrap(self):
        script = (ROOT / 'Install Local AI.command').read_text()
        self.assertIn('uv-aarch64-apple-darwin.tar.gz', script)
        self.assertIn('UV_VERSION="0.12.20"', script)
        self.assertIn('UV_ARCHIVE_SHA256="848fdeb602ff1a1baacd4f6c8b7bdc6cf1ad026a6d9cf59475fda17c179743ca"', script)
        self.assertIn('shasum -a 256', script)
        self.assertNotIn('astral.sh/uv/install.sh', script)
        self.assertIn('UV_EXCLUDE_NEWER="2026-10-16T11:00:00Z"', script)

    def test_comfyui_git_revision_and_hash_are_immutable(self):
        self.assertRegex(installer.COMFY_COMMIT, r'^[0-9a-f]{40}$')
        self.assertRegex(installer.COMFY_SHA256, r'^[0-9a-f]{64}$')
        source = (ROOT / 'installer.py').read_text()
        self.assertIn('archive/{COMFY_COMMIT}.zip', source)
        self.assertIn('archive, COMFY_SHA256', source)
        self.assertNotIn('archive/refs/tags/{COMFY_RELEASE}', source)

    def test_installer_resolves_pinned_pytorch_and_gateway_dependencies(self):
        source = (ROOT / 'installer.py').read_text()
        self.assertEqual((installer.TORCH_VERSION, installer.TORCHVISION_VERSION,
                          installer.TORCHAUDIO_VERSION), ('2.10.0', '0.25.0', '2.10.0'))
        lock = (ROOT / 'locks/comfy-macos-arm64-py312.txt').read_text()
        self.assertIn('torch==2.10.0', lock)
        self.assertIn('torchvision==0.25.0', lock)
        self.assertIn('torchaudio==2.10.0', lock)
        self.assertIn('--require-hashes', source)
        self.assertIn('Pillow==12.0.0', source)
        self.assertIn('requests==2.32.5', source)

    def test_docker_vendor_release_cannot_float(self):
        self.assertIn('/239619/Docker.dmg', docker_setup.URL)
        self.assertRegex(docker_setup.SHA256, r'^[0-9a-f]{64}$')
        source = (ROOT / 'docker_setup.py').read_text()
        self.assertIn('download(URL, image, SHA256)', source)
        self.assertIn("verify(APP)", source)


if __name__ == '__main__':
    unittest.main()
