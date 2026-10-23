"""Owner-authorised, resumable installation of the Krea 2 pixel-art models.

Model weights stay outside the installer archive. Hugging Face gates both
repositories, so the owner must accept the upstream terms and provide a
short-lived read token at install time. The token is never written to disk.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


BASE_REPOSITORY = "krea/Krea-2-Turbo"
LORA_REPOSITORY = "azyg0s/Krea-2-pixelart-lora"
LORA_FILENAME = "pytorch_lora_weights.safetensors"
GENERATION_STEPS = 4
PIXELART_LICENSE_NOTE = (
    "This LoRA is a derivative of Krea 2. Its upstream terms include a "
    "US$1M annual revenue limit for commercial use, content-filtering "
    "requirements for deployments, and the Krea Acceptable Use Policy. "
    "Review and accept the terms on Hugging Face yourself before continuing."
)
API_ROOT = "https://huggingface.co/api/models/"
RESOLVE_ROOT = "https://huggingface.co/"


class PixelArtSetupError(RuntimeError):
    """Installation could not safely fetch or validate the gated models."""


def _safe_relative_path(name: str) -> Path:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise PixelArtSetupError("Hugging Face returned an unsafe repository path.")
    return Path(*path.parts)


def _request(url: str, token: str, *, headers: dict[str, str] | None = None):
    request_headers = {"Authorization": "Bearer " + token, "User-Agent": "LOCAL-AI-installer/1"}
    if headers:
        request_headers.update(headers)
    return Request(url, headers=request_headers)


def fetch_repository_metadata(repository: str, token: str, *, open_url=urlopen) -> dict:
    url = API_ROOT + quote(repository, safe="/") + "?blobs=true"
    try:
        with open_url(_request(url, token), timeout=60) as response:
            data = json.load(response)
    except HTTPError as error:
        if error.code in {401, 403}:
            raise PixelArtSetupError(
                f"Hugging Face denied access to {repository}. Confirm you accepted its terms "
                "and that your read token has access to the gated repository."
            ) from None
        raise PixelArtSetupError(f"Could not read Hugging Face metadata for {repository} (HTTP {error.code}).") from None
    except (OSError, ValueError) as error:
        raise PixelArtSetupError(f"Could not read Hugging Face metadata for {repository}: {error}") from None
    if not isinstance(data, dict) or not isinstance(data.get("sha"), str) or not data.get("sha"):
        raise PixelArtSetupError(f"Hugging Face returned incomplete revision metadata for {repository}.")
    siblings = data.get("siblings")
    if not isinstance(siblings, list) or not siblings:
        raise PixelArtSetupError(f"Hugging Face returned no files for {repository}.")
    return data


def _file_digest(path: Path) -> tuple[str, str, int]:
    sha256 = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while block := source.read(8 * 1024 * 1024):
            size += len(block)
            sha256.update(block)
    # Hugging Face's blobId is Git's blob hash, including this object header.
    sha1 = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as source:
        while block := source.read(8 * 1024 * 1024):
            sha1.update(block)
    git_sha1 = sha1.hexdigest()
    return sha256.hexdigest(), git_sha1, size


def _expected_hash(sibling: dict) -> tuple[str | None, str | None]:
    lfs = sibling.get("lfs")
    if isinstance(lfs, dict):
        oid = lfs.get("oid")
        if isinstance(oid, str) and oid.startswith("sha256:"):
            return oid.split(":", 1)[1], None
    blob = sibling.get("blobId")
    return None, blob if isinstance(blob, str) else None


def _matches(path: Path, sibling: dict) -> bool:
    expected_size = sibling.get("size")
    if isinstance(expected_size, int) and path.stat().st_size != expected_size:
        return False
    expected_sha256, expected_git_sha1 = _expected_hash(sibling)
    actual_sha256, actual_git_sha1, _ = _file_digest(path)
    if expected_sha256:
        return actual_sha256 == expected_sha256
    if expected_git_sha1:
        return actual_git_sha1 == expected_git_sha1
    raise PixelArtSetupError("Hugging Face file metadata has no verifiable digest.")


def _download_file(repository: str, revision: str, sibling: dict, destination: Path, token: str,
                   *, open_url=urlopen, log=logging.info) -> None:
    name = sibling.get("rfilename")
    relative = _safe_relative_path(name) if isinstance(name, str) else None
    if relative is None:
        raise PixelArtSetupError("Hugging Face returned a file without a valid path.")
    target = destination / relative
    if destination.is_symlink() or any(
        (destination / Path(*relative.parts[:index])).is_symlink()
        for index in range(1, len(relative.parts))
    ):
        raise PixelArtSetupError("Refusing a symbolic link in the model installation path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise PixelArtSetupError("Refusing a symbolic link as a model file.")
    if target.is_file() and _matches(target, sibling):
        return
    partial = target.with_name(target.name + ".part")
    if partial.is_symlink():
        raise PixelArtSetupError("Refusing a symbolic link as an interrupted model download.")
    expected_size = sibling.get("size")
    offset = partial.stat().st_size if partial.is_file() else 0
    if isinstance(expected_size, int) and offset > expected_size:
        partial.unlink()
        offset = 0
    url = (RESOLVE_ROOT + quote(repository, safe="/") + "/resolve/" + quote(revision, safe="") +
           "/" + quote(name, safe="/"))
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    try:
        response = open_url(_request(url, token, headers=headers), timeout=120)
        status = getattr(response, "status", getattr(response, "code", 200))
        if offset and status != 206:
            response.close()
            offset = 0
            response = open_url(_request(url, token), timeout=120)
        mode = "ab" if offset else "wb"
        with response, partial.open(mode) as output:
            total = expected_size or 0
            while block := response.read(8 * 1024 * 1024):
                output.write(block)
                if total:
                    log("Downloaded %s: %.0f/%.0f MB", target.name,
                        output.tell() / (1024 * 1024), total / (1024 * 1024))
    except HTTPError as error:
        if error.code in {401, 403}:
            raise PixelArtSetupError(
                f"Hugging Face denied access to {repository}. Confirm the repository terms and token access."
            ) from None
        raise PixelArtSetupError(f"Download failed for {repository}/{name} (HTTP {error.code}).") from None
    except OSError as error:
        raise PixelArtSetupError(f"Download failed for {repository}/{name}: {error}") from None
    if isinstance(expected_size, int) and partial.stat().st_size != expected_size:
        raise PixelArtSetupError(f"Downloaded size does not match Hugging Face metadata for {target.name}.")
    if not _matches(partial, sibling):
        raise PixelArtSetupError(f"Downloaded digest does not match Hugging Face metadata for {target.name}.")
    os.replace(partial, target)


def install_repositories(root: Path, token: str, *, metadata_fetch=fetch_repository_metadata,
                         file_download=_download_file, free_bytes=None) -> dict:
    root = Path(root)
    model_root = root / "models" / "pixelart"
    model_root.mkdir(parents=True, exist_ok=True)
    repositories = (BASE_REPOSITORY, LORA_REPOSITORY)
    metadata = {name: metadata_fetch(name, token) for name in repositories}
    total = sum(sibling.get("size", 0) for info in metadata.values()
                for sibling in info["siblings"] if isinstance(sibling.get("size", 0), int))
    available = free_bytes(model_root) if free_bytes else shutil.disk_usage(model_root).free
    if available < total + 2 * 1024**3:
        raise PixelArtSetupError(
            f"Krea 2 pixel-art models need about {total / (1024**3):.1f} GB plus 2 GB working space; "
            f"only {available / (1024**3):.1f} GB is free."
        )
    manifest = {
        "base_model": {"repository": BASE_REPOSITORY, "revision": metadata[BASE_REPOSITORY]["sha"]},
        "pixelart_lora": {"repository": LORA_REPOSITORY, "revision": metadata[LORA_REPOSITORY]["sha"]},
        "generation": {"steps": GENERATION_STEPS, "guidance_scale": 0.0,
                       "width": 512, "height": 512, "prompt_prefix": "pixel art 32x32 game icon, ",
                       "prompt_suffix": ", dark outline, plain magenta background"},
        "weights_verified": False,
    }
    for repository in repositories:
        info = metadata[repository]
        destination = model_root / repository
        for sibling in info["siblings"]:
            file_download(repository, info["sha"], sibling, destination, token)
        manifest_key = "base_model" if repository == BASE_REPOSITORY else "pixelart_lora"
        manifest[manifest_key]["files"] = len(info["siblings"])
    lora_path = model_root / LORA_REPOSITORY / LORA_FILENAME
    pipeline_index = model_root / BASE_REPOSITORY / "model_index.json"
    if not lora_path.is_file() or not pipeline_index.is_file():
        raise PixelArtSetupError("The downloaded repositories are missing the required LoRA or Diffusers pipeline file.")
    manifest["weights_verified"] = True
    manifest_path = model_root / "model-manifest.json"
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, manifest_path)
    return manifest


def install_if_selected(root: Path, *, input_fn=input, secret_fn=getpass.getpass, output=print,
                        metadata_fetch=fetch_repository_metadata) -> bool:
    output("\nOptional model component: Krea 2 Turbo + Pixel-art LoRA")
    output("The model produces 32x32 icons. The two Hugging Face repositories are gated.")
    selected = input_fn("Install this model component now? [y/N] ").strip().lower()
    if selected not in {"y", "yes"}:
        output("Skipping Krea 2 pixel-art models. You can install them in a later installer run.")
        return False
    output(PIXELART_LICENSE_NOTE)
    accepted = input_fn(
        "Have you personally reviewed and accepted Hugging Face access conditions "
        "for both repositories? [y/N] "
    ).strip().lower()
    if accepted not in {"y", "yes"}:
        output("Skipping model downloads. The installer cannot accept upstream terms for you.")
        return False
    token = secret_fn("Hugging Face read token (used for this install only; not saved): ").strip()
    if not token:
        output("Skipping model downloads because no Hugging Face token was provided.")
        return False
    install_repositories(root, token, metadata_fetch=metadata_fetch)
    output("Krea 2 Turbo and its pixel-art LoRA were downloaded and verified.")
    return True
