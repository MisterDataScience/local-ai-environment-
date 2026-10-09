"""Bounded, local-only OpenAI image-part decoder for Ollama vision input.

Never fetch a user-supplied URL: only inline JPEG/PNG/WebP data are accepted.
Frames and metadata are discarded, and pixels are size-bounded before inference.
"""
import base64
import binascii
from io import BytesIO
import re

DATA_URL = re.compile(r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)$")
MAX_IMAGE_TEXT = 1_500_000
MAX_IMAGE_PIXELS = 16_000_000
MAX_EDGE = 1536
MAX_IMAGES_PER_MESSAGE = 2
MAX_IMAGES_PER_REQUEST = 4


def normalize_data_image(url):
    if not isinstance(url, str) or len(url) > MAX_IMAGE_TEXT:
        raise ValueError("Image is missing or exceeds the inline image limit")
    matched = DATA_URL.fullmatch(url)
    if not matched:
        raise ValueError("Only inline JPEG, PNG or WebP data URLs are supported; no network fetch")
    try:
        data = base64.b64decode(matched[2], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid base64-encoded image") from None
    if not 0 < len(data) <= 1_000_000:
        raise ValueError("Image exceeds 1 MB decoded")
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
        with Image.open(BytesIO(data)) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported image encoding")
            if opened.width < 1 or opened.height < 1 or opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions exceed the vision budget")
            if getattr(opened, "n_frames", 1) != 1:
                raise ValueError("Animated images are not supported")
            image = ImageOps.exif_transpose(opened)
            image.thumbnail((MAX_EDGE, MAX_EDGE))
            converted = Image.new("RGB", image.size, (255, 255, 255))
            if "A" in image.getbands():
                converted.paste(image.convert("RGBA"), mask=image.getchannel("A"))
            else:
                converted.paste(image.convert("RGB"))
            output = BytesIO()
            converted.save(output, format="JPEG", quality=82, optimize=True)
            raw = output.getvalue()
            if len(raw) > 1_000_000:
                raise ValueError("Normalized image exceeds 1 MB")
            return base64.b64encode(raw).decode("ascii")
    except (OSError, UnidentifiedImageError):
        raise ValueError("Cannot decode the supplied image") from None


def parts_to_message(content, role):
    """Return (plain_text, [Ollama base64 image strings])."""
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list) or not content or len(content) > 32:
        raise ValueError("Message content must be text or a bounded part list")
    parts, images = [], []
    for part in content:
        if not isinstance(part, dict):
            raise ValueError("Invalid content part")
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            parts.append(part["text"])
        elif part.get("type") == "image_url" and role == "user":
            raw = part.get("image_url")
            if not isinstance(raw, dict) or set(raw) - {"url", "detail"}:
                raise ValueError("Invalid image_url structure")
            if raw.get("detail", "auto") not in {"auto", "high", "low"}:
                raise ValueError("Invalid image detail hint")
            if len(images) >= MAX_IMAGES_PER_MESSAGE:
                raise ValueError("Too many images in one message")
            images.append(normalize_data_image(raw.get("url")))
        else:
            raise ValueError("Unsupported content part; use text or inline image_url")
    if not parts and not images:
        raise ValueError("Empty content parts")
    return "\n".join(parts), images
