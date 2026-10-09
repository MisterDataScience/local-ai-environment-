"""Small verified patch to pinned WebUI's pre-filter remote image fetch.

Inlet filters run after WebUI's native URL conversion. Defer that conversion
to our owned local-upload filter instead, so external image URLs cannot cause
a direct network fetch before gateway validation.
"""
import hashlib
from pathlib import Path

ORIGINAL_SHA256 = '760204c67d2fee9a813bcc5d9551052f779278f9eeda10bc769172a5f50575a8'
REPLACEMENT = '''async def get_image_base64_from_url(url: str, user=None) -> Optional[str]:
    # LOCAL_AI_LOCAL_IMAGES_V1: conversion belongs to the owned local filter.
    # Return None so native middleware retains the original reference.
    return None'''
PDF_ORIGINAL = '''                loader = PyPDFLoader(
                    file_path,
                    extract_images=self.kwargs.get('PDF_EXTRACT_IMAGES'),
                    mode=self.kwargs.get('PDF_LOADER_MODE', 'page'),
                )'''
PDF_REPLACEMENT = '''                # LOCAL_AI_NATIVE_PDF_V1: bounded local Apple PDFKit/Vision.
                from pathlib import Path
                control = str(Path(os.environ['LOCAL_AI_ROOT']) / 'control')
                if control not in sys.path:
                    sys.path.insert(0, control)
                from native_pdf_loader import LocalAIPDFLoader
                loader = LocalAIPDFLoader(file_path)'''


def harden(root):
    candidates = list((root / 'webui/.venv/lib').glob('python*/site-packages/open_webui/utils/files.py'))
    if len(candidates) != 1 or candidates[0].is_symlink():
        raise RuntimeError('Pinned WebUI image resolver could not be identified')
    path = candidates[0]
    source = path.read_text()
    begin = source.index('async def get_image_base64_from_url(')
    end = source.index('\n\nasync def get_image_url_from_base64', begin)
    original = source[begin:end]
    if original == REPLACEMENT:
        return
    if hashlib.sha256(original.encode()).hexdigest() != ORIGINAL_SHA256:
        raise RuntimeError('WebUI image resolver differs from pinned 0.11.1; no unverified patch applied')
    path.write_text(source[:begin] + REPLACEMENT + source[end:])


def harden_pdf(root):
    candidates = list((root / 'webui/.venv/lib').glob('python*/site-packages/open_webui/retrieval/loaders/main.py'))
    if len(candidates) != 1 or candidates[0].is_symlink():
        raise RuntimeError('Pinned WebUI PDF loader could not be identified')
    path = candidates[0]
    source = path.read_text()
    if PDF_REPLACEMENT in source and PDF_ORIGINAL not in source:
        return
    if source.count(PDF_ORIGINAL) != 1:
        raise RuntimeError('Native PDF loader differs from pinned WebUI; no unverified patch applied')
    path.write_text(source.replace(PDF_ORIGINAL, PDF_REPLACEMENT))
