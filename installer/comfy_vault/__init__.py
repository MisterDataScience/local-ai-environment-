"""Bundled ComfyUI output nodes: PNG/MP4 directly into the checked vault."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.environ['LOCAL_AI_CONTROL'])
from vault_media import save_image, encode_video


def configuration():
    return {'vault': json.loads(os.environ['LOCAL_AI_VAULT'])}


def rgb(frame):
    import numpy as np
    return np.clip(frame.cpu().numpy() * 255.0, 0, 255).astype(np.uint8)[..., :3]


def result(name):
    return {'ui': {'images': [{'filename': name, 'subfolder': 'Media', 'type': 'output'}]}}


class LocalAIVaultImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',)}}
    RETURN_TYPES = ()
    FUNCTION = 'save'
    OUTPUT_NODE = True
    CATEGORY = 'Local AI'

    def save(self, images):
        from PIL import Image
        if len(images) != 1:
            raise ValueError('Vault image workflow currently requires one image.')
        return result(save_image(configuration(), Image.fromarray(rgb(images[0]))))


class LocalAIVaultVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'fps': ('FLOAT', {'default': 12.0, 'min': 1.0, 'max': 60.0})}}
    RETURN_TYPES = ()
    FUNCTION = 'save'
    OUTPUT_NODE = True
    CATEGORY = 'Local AI'

    def save(self, images, fps=12.0):
        if not 1 <= len(images) <= 512:
            raise ValueError('Expected 1 to 512 video frames')
        height, width = int(images.shape[1]), int(images.shape[2])
        name = encode_video(configuration(), (rgb(frame).tobytes() for frame in images),
                            width, height, os.environ['LOCAL_AI_FFMPEG'], fps)
        return result(name)


NODE_CLASS_MAPPINGS = {'LocalAIVaultImage': LocalAIVaultImage, 'LocalAIVaultVideo': LocalAIVaultVideo}
