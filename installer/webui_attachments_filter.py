"""
title: Local AI attachments
version: 1.0.0
description: Owned local images and Apple PDFKit/Vision evidence.
"""
import os
from pathlib import Path
import sys


class Filter:
    async def inlet(self, body: dict, __user__: dict = None) -> dict:
        from open_webui.models.files import Files
        from open_webui.config import UPLOAD_DIR
        root = Path(os.environ['LOCAL_AI_ROOT']).resolve(strict=True)
        control = str(root / 'control')
        if control not in sys.path:
            sys.path.insert(0, control)
        from chat_attachments import inlet
        return await inlet(body, __user__, root, UPLOAD_DIR, Files.get_file_by_id)
