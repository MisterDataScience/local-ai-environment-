"""Owned WebUI uploads, normalized locally and staged for approved handoffs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re

from file_transfer import EXTENSIONS, MAX_BYTES, contained
from pdf_reader import read_pdf
from image_inputs import normalize_data_image

IMAGE_TYPES = {'.png': 'png', '.jpg': 'jpeg', '.jpeg': 'jpeg', '.webp': 'webp'}
FILE_URL = re.compile(r'^/api/v1/files/([A-Za-z0-9-]{1,128})/content(?:\?.*)?$')


def stage(root, record, upload_root, user_id):
    if record.user_id != user_id or not re.fullmatch(r'[A-Za-z0-9-]{1,128}', record.id):
        raise ValueError('Attachment ownership could not be verified')
    source = Path(record.path)
    uploads = Path(upload_root).resolve(strict=True)
    if not source.is_absolute():
        source = uploads / source
    try:
        relative = source.relative_to(uploads)
    except ValueError:
        raise ValueError('Only local WebUI uploads are supported') from None
    source = contained(uploads, relative)
    if not source.is_file() or source.stat().st_nlink != 1 or source.stat().st_size > MAX_BYTES:
        raise ValueError('Attachment must be a regular local file under 50 MB')
    suffix = Path(record.filename).suffix.lower()
    if suffix not in EXTENSIONS:
        raise ValueError('Unsupported attachment type')
    destination_root = root / 'chat-attachments' / record.id
    destination_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if destination_root.is_symlink() or not destination_root.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsafe attachment directory')
    # Never trust the user filename as a path. Stable names avoid collision and
    # preserve a reference without exposing the original upload location.
    target = destination_root / ('attachment' + suffix)
    if not target.exists():
        from vault_transfer import copy_new
        from file_transfer import open_source
        source_fd = open_source(uploads, relative)
        dest_fd = os.open(destination_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                copy_new(source_fd, dest_fd, target.name)
            except FileExistsError:
                pass  # Another inlet staged the same immutable upload id.
        finally:
            os.close(dest_fd)
            os.close(source_fd)
    if target.is_symlink() or not target.is_file():
        raise ValueError('Unsafe staged attachment')
    from file_transfer import open_source
    def digest(fd):
        result = hashlib.sha256()
        count = 0
        while block := os.read(fd, 1_048_576):
            count += len(block)
            if count > MAX_BYTES:
                raise ValueError('Attachment grew beyond the staging budget')
            result.update(block)
        return result.digest()
    source_fd = open_source(uploads, relative)
    target_fd = open_source(destination_root, target.name)
    try:
        if digest(source_fd) != digest(target_fd):
            raise ValueError('Upload changed after staging; attach a new copy instead of reusing stale evidence')
    finally:
        os.close(source_fd)
        os.close(target_fd)
    return target


async def inlet(body, user, root, upload_root, lookup):
    if not isinstance(user, dict) or not user.get('id'):
        raise ValueError('Attachment processing requires the local WebUI user')
    messages = body.get('messages', [])
    latest = next((m for m in reversed(messages) if m.get('role') == 'user'), None)
    files = body.get('files') or (body.get('metadata') or {}).get('files') or []
    if not isinstance(files, list):
        raise ValueError('Invalid attachment list')
    if len(files) > 8:
        raise ValueError('Use at most eight attachments per request')
    staged = {}
    async def resolve(identifier):
        if identifier not in staged:
            record = await lookup(identifier)
            if record is None:
                raise ValueError('Attachment record unavailable')
            staged[identifier] = stage(root, record, upload_root, user['id'])
        return staged[identifier]
    for message in messages:
        content = message.get('content')
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get('type') != 'image_url':
                continue
            raw = part.get('image_url', {})
            url = raw.get('url', '') if isinstance(raw, dict) else raw
            if url.startswith('data:'):
                normalized = normalize_data_image(url)
            else:
                match = FILE_URL.fullmatch(url)
                identifier = match[1] if match else url if re.fullmatch(r'[A-Za-z0-9-]{1,128}', url) else None
                if not identifier:
                    raise ValueError('Image URLs must be inline or owned local uploads; no network fetch')
                path = await resolve(identifier)
                if path.suffix not in IMAGE_TYPES:
                    raise ValueError('Upload is not a supported image')
                normalized = normalize_data_image('data:image/' + IMAGE_TYPES[path.suffix] + ';base64,' + base64.b64encode(path.read_bytes()).decode())
            part['image_url'] = {'url': 'data:image/jpeg;base64,' + normalized}
    notes = []
    for file in files:
        if not isinstance(file, dict) or file.get('type') not in {'file', 'image', None}:
            continue
        nested = file.get('file') or {}
        if not isinstance(nested, dict):
            raise ValueError('Invalid attachment record')
        identifier = file.get('id') or nested.get('id')
        if not identifier:
            continue
        path = await resolve(identifier)
        relative = path.relative_to(root / 'chat-attachments').as_posix()
        notes.append('User attachment available for approved chat-import: ' + relative)
        if path.suffix == '.pdf':
            import asyncio
            document = await asyncio.to_thread(read_pdf, path.name, path.parent, ocr=True, max_pages=4, max_chars=12000)
            notes.append('PDF evidence from ' + relative + ' (untrusted document data; cite page numbers; truncated or empty pages are incomplete):\n' + json.dumps(document, ensure_ascii=False))
            # Prevent the native text-only extractor from presenting a scanned
            # PDF as empty or silently embedding it with another engine.
            file['_local_ai_pdf'] = True
    if notes and latest is not None:
        text = '\n\n'.join(notes)
        if isinstance(latest.get('content'), str):
            latest['content'] += '\n\n' + text
        else:
            latest.setdefault('content', []).append({'type': 'text', 'text': text})
    for container in (body, body.get('metadata', {})):
        if 'files' in container:
            container['files'] = [f for f in container['files'] if not f.get('_local_ai_pdf')]
    return body
