import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from pixelart_runner import generate, search, validate_batch


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.models = root / "models" / "pixelart"
        self.models.mkdir(parents=True)
        self.output = root / "output"
        (self.models / "model-manifest.json").write_text(json.dumps({
            "weights_verified": True,
            "base_model": {"revision": "base-revision"},
            "pixelart_lora": {"revision": "lora-revision"},
            "generation": {"steps": 4, "guidance_scale": 0.0, "width": 512,
                           "height": 512, "prompt_prefix": "pixel art, ",
                           "prompt_suffix": ", plain magenta background"},
        }))
        self.batch = {"id": "icons", "sprites": [
            {"id": "red-apple-01", "prompt": "a red apple", "tags": ["apple", "icon", "pixel-art", "inventory"], "seed": 123},
            {"id": "red-apple-02", "prompt": "a red apple with a leaf", "tags": ["apple", "icon", "pixel-art", "inventory"], "seed": 124},
        ]}

    def test_generation_resumes_without_reloading_or_overwriting(self):
        calls = []

        def render(prompt, seed, settings):
            calls.append((prompt, seed, settings["steps"]))
            image = Image.new("RGB", (512, 512), (255, 0, 255))
            image.putpixel((8, 8), (190, 12, 15))
            return image

        first = generate(self.batch, self.models, self.output, renderer=render)
        second = generate(self.batch, self.models, self.output, renderer=render)
        self.assertEqual(len(calls), 2)
        self.assertEqual(first, second)
        self.assertEqual(first["count"], 2)
        self.assertEqual(len(search(self.output, "apple")), 2)
        sprite = Image.open(self.output / "icons/sprites/red-apple-01.png")
        self.assertEqual(sprite.size, (32, 32))
        self.assertEqual(sprite.getpixel((0, 0)), (190, 12, 15, 255))
        self.assertEqual(sprite.getpixel((1, 0))[3], 0)
        self.assertEqual(first["records"][0]["model_revisions"]["pixelart_lora"], "lora-revision")

    def test_rejects_modified_brief_and_corrupt_existing_output(self):
        render = lambda *args: Image.new("RGB", (512, 512), (255, 0, 255))
        generate(self.batch, self.models, self.output, renderer=render)
        changed = json.loads(json.dumps(self.batch))
        changed["sprites"][0]["prompt"] = "a different object"
        with self.assertRaisesRegex(ValueError, "immutable brief"):
            generate(changed, self.models, self.output, renderer=render)
        (self.output / "icons/sprites/red-apple-01.png").write_bytes(b"corrupt")
        with self.assertRaisesRegex(RuntimeError, "failed verification"):
            generate(self.batch, self.models, self.output, renderer=render)

    def test_rejects_unsearchable_tags_and_duplicate_ids(self):
        self.batch["sprites"][0]["tags"] = ["Apple", "icon", "pixel-art"]
        with self.assertRaisesRegex(ValueError, "lowercase tags"):
            validate_batch(self.batch)
        self.batch["sprites"][0]["tags"] = ["apple", "icon", "pixel-art"]
        self.batch["sprites"][1]["id"] = self.batch["sprites"][0]["id"]
        with self.assertRaisesRegex(ValueError, "repeated sprite ID"):
            validate_batch(self.batch)


if __name__ == "__main__":
    unittest.main()
