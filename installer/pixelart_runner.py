"""Resumable local Krea 2 Turbo + pixel-art LoRA batch generation.

One process loads the pipeline once for the complete batch. Each finished sprite
has an atomic JSON receipt, so a restart can skip verified outputs safely.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from PIL import Image

TAG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IDENT = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
MAX_SPRITES = 1000


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".pixelart-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_batch(batch: dict) -> list[dict]:
    if not isinstance(batch, dict) or not IDENT.fullmatch(batch.get("id", "")):
        raise ValueError("Invalid batch ID")
    sprites = batch.get("sprites")
    if not isinstance(sprites, list) or not 1 <= len(sprites) <= MAX_SPRITES:
        raise ValueError("A batch needs 1 to 1000 sprites")
    ids = set()
    for row in sprites:
        if not isinstance(row, dict) or set(row) != {"id", "prompt", "tags", "seed"}:
            raise ValueError("Each sprite needs id, prompt, tags and seed")
        sid, prompt, tags, seed = (row[k] for k in ("id", "prompt", "tags", "seed"))
        if not isinstance(sid, str) or not IDENT.fullmatch(sid) or sid in ids:
            raise ValueError("Invalid or repeated sprite ID")
        ids.add(sid)
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000:
            raise ValueError("Invalid sprite prompt")
        if (not isinstance(tags, list) or not 3 <= len(tags) <= 8 or
                any(not isinstance(tag, str) or not TAG.fullmatch(tag) for tag in tags) or
                len(set(tags)) != len(tags)):
            raise ValueError("Each sprite needs 3 to 8 unique lowercase tags")
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("Invalid deterministic seed")
    return sprites


def load_pipeline(model_root: Path):
    """Import optional GPU dependencies only when generation starts."""
    import torch
    from diffusers import Krea2Pipeline

    if not torch.backends.mps.is_available() and not torch.cuda.is_available():
        raise RuntimeError("Krea generation needs an available MPS or CUDA device")
    device = "mps" if torch.backends.mps.is_available() else "cuda"
    base = model_root / "krea" / "Krea-2-Turbo"
    lora = model_root / "azyg0s" / "Krea-2-pixelart-lora"
    pipeline = Krea2Pipeline.from_pretrained(str(base), dtype=torch.bfloat16, local_files_only=True)
    pipeline.load_lora_weights(str(lora), weight_name="pytorch_lora_weights.safetensors")
    pipeline.to(device)

    def render(prompt: str, seed: int, settings: dict) -> Image.Image:
        generator = torch.Generator(device=device).manual_seed(seed)
        return pipeline(prompt, height=settings["height"], width=settings["width"],
                        num_inference_steps=settings["steps"], guidance_scale=settings["guidance_scale"],
                        generator=generator).images[0]
    return render


def extract(image: Image.Image) -> Image.Image:
    """Take the centre pixel of each 16x16 block, then colour-key magenta."""
    if image.size != (512, 512):
        raise ValueError("Expected a 512x512 Krea render")
    source = image.convert("RGB")
    sprite = Image.new("RGBA", (32, 32))
    for y in range(32):
        for x in range(32):
            r, g, b = source.getpixel((x * 16 + 8, y * 16 + 8))
            alpha = 0 if r >= 200 and b >= 200 and g <= 105 else 255
            sprite.putpixel((x, y), (r, g, b, alpha))
    return sprite


def generate(batch: dict, model_root: Path, output_root: Path, *, renderer=None) -> dict:
    sprites = validate_batch(batch)
    manifest = _json(model_root / "model-manifest.json")
    if manifest.get("weights_verified") is not True:
        raise RuntimeError("Verified Krea model manifest is required")
    settings = manifest["generation"]
    if any(settings.get(k) != v for k, v in
           (("steps", 4), ("guidance_scale", 0.0), ("width", 512), ("height", 512))):
        raise RuntimeError("Unexpected Krea pixel-art generation settings")
    target = output_root / batch["id"]
    if output_root.is_symlink() or target.is_symlink():
        raise PermissionError("Refusing a symlinked output directory")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    batch_spec = json.dumps(batch, sort_keys=True, separators=(",", ":")).encode()
    batch_digest = hashlib.sha256(batch_spec).hexdigest()
    pinned = target / "batch.json"
    if pinned.exists():
        if _json(pinned).get("digest") != batch_digest:
            raise ValueError("Batch ID already belongs to a different immutable brief")
    else:
        _atomic(pinned, json.dumps({"digest": batch_digest, "batch": batch}, sort_keys=True).encode())
    records = []
    for row in sprites:
        sid = row["id"]
        path = target / "sprites" / (sid + ".png")
        receipt = target / "records" / (sid + ".json")
        if receipt.exists():
            record = _json(receipt)
            if (not path.is_file() or path.is_symlink() or
                    hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256") or
                    record.get("batch_digest") != batch_digest):
                raise RuntimeError("Existing sprite receipt or image failed verification: " + sid)
            records.append(record)
            continue
        if path.exists() or path.is_symlink():
            raise RuntimeError("Uncommitted sprite output requires manual recovery: " + sid)
        if renderer is None:
            renderer = load_pipeline(model_root)
        prompt = settings.get("prompt_prefix", "") + row["prompt"] + settings.get("prompt_suffix", "")
        image = extract(renderer(prompt, row["seed"], settings))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=target) as tmp:
            temporary = Path(tmp.name)
        try:
            image.save(temporary, format="PNG")
            payload = temporary.read_bytes()
            _atomic(path, payload)
        finally:
            temporary.unlink(missing_ok=True)
        record = dict(id=sid, batch=batch["id"], batch_digest=batch_digest,
                      prompt=row["prompt"], tagged_prompt=row["prompt"] + "\n[TAGS: " + ", ".join(row["tags"]) + "]",
                      rendered_prompt=prompt, tags=row["tags"], seed=row["seed"],
                      model_revisions={k: manifest[k]["revision"] for k in ("base_model", "pixelart_lora")},
                      settings={k: settings[k] for k in ("steps", "guidance_scale", "width", "height")},
                      file="sprites/" + sid + ".png", sha256=hashlib.sha256(payload).hexdigest())
        _atomic(receipt, json.dumps(record, sort_keys=True).encode())
        records.append(record)
    return dict(batch=batch["id"], count=len(records), records=records)


def search(output_root: Path, tag: str) -> list[dict]:
    if not TAG.fullmatch(tag):
        raise ValueError("Invalid tag")
    return [record for receipt in output_root.glob("*/records/*.json")
            if (record := _json(receipt)) and tag in record.get("tags", [])]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    args = parser.parse_args(argv)
    result = generate(_json(args.batch), args.models, args.output)
    print(json.dumps({"batch": result["batch"], "count": result["count"]}))


if __name__ == "__main__":
    main()
