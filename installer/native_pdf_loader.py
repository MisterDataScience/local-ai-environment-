"""Adapt the existing Apple PDF reader to WebUI's native upload loader."""
import json
import os
from pathlib import Path


class LocalAIPDFLoader:
    def __init__(self, file_path, **kwargs):
        self.path = Path(file_path)

    def load(self):
        from langchain_core.documents import Document
        from pdf_reader import read_pdf
        from open_webui.config import UPLOAD_DIR
        uploads = Path(UPLOAD_DIR).resolve(strict=True)
        if not self.path.is_absolute():
            raise ValueError('Native PDF upload must have a local path')
        relative = self.path.relative_to(uploads)
        result = read_pdf(relative, uploads, ocr=True, max_pages=8, max_chars=24000)
        # Store explicit page/provenance and continuation information in the
        # native file record. Empty scans stay visibly incomplete.
        return [Document(page_content=json.dumps({
            'notice': 'Local Apple PDFKit/Vision evidence. Empty, truncated or OCR-error pages are incomplete. Use read_attachment_pdf to continue.',
            **result}, ensure_ascii=False), metadata={'source': self.path.name, 'local_ai_pdf': True})]
