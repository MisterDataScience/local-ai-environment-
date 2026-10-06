"""Descriptor-based encrypted output: never stages generated frames on local disk."""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import uuid

from vault_tools import mounted_root, directory, DIR_FLAGS

MEDIA_NAME = re.compile(r'^[0-9a-f]{32}\.(png|webp|mp4|webm)$')


def same_mount(config, original_fd):
    with mounted_root(config) as current:
        before, after = os.fstat(original_fd), os.fstat(current)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise RuntimeError('Vault changed during operation. No fallback storage is used.')


@contextmanager
def output_directory(config, category='Media'):
    if category not in {'Media', 'Backups', 'Migration'}:
        raise ValueError('Invalid output category')
    with mounted_root(config) as root:
        with directory(root, ['Outputs' if category == 'Media' else 'Archive']) as parent:
            try:
                os.mkdir(category, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            with directory(parent, [category]) as folder:
                yield root, folder


@contextmanager
def atomic_output(config, suffix, category='Media'):
    if suffix not in {'.png', '.mp4', '.webp', '.webm', '.zip'}:
        raise ValueError('Unsupported output type')
    name = uuid.uuid4().hex + suffix
    temporary = '.' + name + '.partial'
    with output_directory(config, category) as (root, parent):
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                yield out, name, root
                out.flush()
                os.fsync(out.fileno())
            same_mount(config, root)
            os.rename(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except OSError:
                pass


@contextmanager
def open_media(config, name):
    if not isinstance(name, str) or not MEDIA_NAME.fullmatch(name):
        raise ValueError('Invalid media filename')
    with mounted_root(config) as root:
        with directory(root, ['Outputs', 'Media']) as parent:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as source:
                s = os.fstat(source.fileno())
                if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
                    raise ValueError('Media must be a regular file')
                yield source, s.st_size, root


def save_image(config, image):
    with atomic_output(config, '.png') as (out, name, root):
        image.save(out, format='PNG')
    return name


def encode_video(config, frames, width, height, ffmpeg, fps=12.0):
    if not (0 < width <= 4096 and 0 < height <= 4096 and 0 < fps <= 60):
        raise ValueError('Unsupported video dimensions or frame rate')
    with atomic_output(config, '.mp4') as (out, name, root):
        # FFmpeg consumes RGB bytes on stdin and sends the MP4 to the already-open
        # encrypted file descriptor. There are no temporary PNGs or output paths.
        process = subprocess.Popen([str(ffmpeg), '-v', 'error', '-nostdin', '-f', 'rawvideo',
            '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', str(fps), '-i', 'pipe:0',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags',
            'frag_keyframe+empty_moov', '-f', 'mp4', 'pipe:1'],
            stdin=subprocess.PIPE, stdout=out, stderr=subprocess.DEVNULL)
        watchdog = threading.Timer(180, lambda: process.kill() if process.poll() is None else None)
        watchdog.daemon = True
        watchdog.start()
        try:
            count = 0
            for frame in frames:
                same_mount(config, root)
                count += 1
                if count > 512 or len(frame) != width * height * 3:
                    raise ValueError('Invalid or excessive video frames')
                process.stdin.write(frame)
            process.stdin.close()
            if not count or process.wait(timeout=180) != 0:
                raise RuntimeError('Video encoding failed; incomplete output was discarded.')
        finally:
            watchdog.cancel()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)
            if process.stdin and not process.stdin.closed:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
    return name


# Only the bundled generation nodes are accepted while vault mode is active.
ALLOWED = {'CheckpointLoaderSimple', 'CLIPTextEncode', 'EmptyLatentImage', 'KSampler',
           'VAEDecode', 'SaveImage', 'CLIPLoader', 'LTXVConditioning', 'EmptyLTXVLatentVideo',
           'LTXVScheduler', 'KSamplerSelect', 'SamplerCustom', 'SaveAnimatedWEBP'}


def encrypted_workflow(workflow, kind):
    import copy
    result = copy.deepcopy(workflow)
    saves = 0
    expected = 'SaveImage' if kind == 'image' else 'SaveAnimatedWEBP'
    for node in result.values():
        name = node.get('class_type')
        if name not in ALLOWED:
            raise ValueError(f'Node {name!r} is not approved for vault-mode rendering.')
        if name in {'SaveImage', 'SaveAnimatedWEBP'}:
            if name != expected:
                raise ValueError('Unexpected output node for this generation type')
            saves += 1
            inputs = {'images': node['inputs']['images']}
            if kind == 'video':
                inputs['fps'] = node['inputs'].get('fps', 12.0)
            node['class_type'] = 'LocalAIVaultImage' if kind == 'image' else 'LocalAIVaultVideo'
            node['inputs'] = inputs
    if saves != 1:
        raise ValueError('Vault workflows require exactly one supported output node.')
    return result
