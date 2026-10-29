import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

from pixelart_runner import generate
from pixelart_review import Review


class ReviewTests(unittest.TestCase):
    def test_paged_review_survives_restart_and_exports_only_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            models = root / "models"
            models.mkdir()
            (models / "model-manifest.json").write_text(json.dumps({
                "weights_verified": True, "base_model": {"revision": "base"},
                "pixelart_lora": {"revision": "lora"},
                "generation": {"steps": 4, "guidance_scale": 0.0, "width": 512, "height": 512}}))
            batch = {"id": "sample", "sprites": [
                {"id": "apple", "prompt": "apple", "tags": ["apple", "icon", "pixel-art"], "seed": 1},
                {"id": "pear", "prompt": "pear", "tags": ["pear", "icon", "pixel-art"], "seed": 2}]}
            output = root / "batches"
            generate(batch, models, output, renderer=lambda *args: Image.new("RGB", (512, 512), "red"))
            review = Review(output)
            page = review.page("sample", limit=1)
            self.assertEqual((page["total"], len(page["records"]), page["has_more"]), (2, 1, True))
            self.assertEqual(len(review.page("sample", tag="apple")["records"]), 1)
            review.decide("sample", "apple", "keep", "Suitable")
            review.decide("sample", "pear", "reject")
            self.assertEqual(Review(output).page("sample")["records"][0]["review"]["decision"], "keep")
            with zipfile.ZipFile(io.BytesIO(review.export_kept("sample"))) as archive:
                self.assertEqual(set(archive.namelist()), {"sprites/apple.png", "manifest.json"})
                self.assertEqual(json.loads(archive.read("manifest.json"))["records"][0]["tags"][0], "apple")

    def test_rejects_cross_batch_ids_and_corrupted_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sample").mkdir()
            (root / "sample/batch.json").write_text("{}")
            review = Review(root)
            with self.assertRaisesRegex(ValueError, "Invalid batch ID"):
                review.page("../sample")
            with self.assertRaisesRegex(ValueError, "Sprite is not in the batch"):
                review.decide("sample", "missing", "keep")


if __name__ == "__main__":
    unittest.main()
