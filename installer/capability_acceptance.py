"""Real ordinary-chat image/PDF acceptance against the installed Mac.

Synthetic fixtures only. Never changes modes, unlocks a vault or approves
agent operations. Unperformed physical and UI journeys remain pending.
"""
import argparse
import io
import json
from pathlib import Path
import secrets
from urllib.request import Request, build_opener, ProxyHandler

from common import http
from context_settings import NoRedirect
from scheduled_tasks import atomic_json


def webui(path, payload=None, token=None, raw=None, content_type='application/json'):
    headers = {'Content-Type': content_type}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = raw if raw is not None else None if payload is None else json.dumps(payload).encode()
    with build_opener(ProxyHandler({}), NoRedirect()).open(Request('http://127.0.0.1:8081' + path, data=data, headers=headers), timeout=1900) as response:
        return json.load(response)


def upload(name, data, mime, token, process=False):
    boundary = 'local-ai-' + secrets.token_hex(16)
    raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
           + data + f'\r\n--{boundary}--\r\n'.encode())
    return webui('/api/v1/files/?process=' + str(process).lower() + '&process_in_background=false', token=token, raw=raw,
                 content_type='multipart/form-data; boundary=' + boundary)


def run(root):
    from PIL import Image, ImageDraw, ImageFont
    config = json.loads((root / 'control/config.json').read_text())
    mode = http('http://127.0.0.1:8001/control/mode', key=config['api_key'])
    if mode['mode'] == 'gaming' or mode['transitioning'] or mode['error']:
        raise RuntimeError('Acceptance requires ready Normal or Max; the test never changes your mode')
    visible = http('http://127.0.0.1:8001/v1/models', key=config['api_key'])['data']
    candidates = [m['id'] for m in visible if 'qwen3.5' in config['text_models'][m['id']]['model'].lower()]
    if not candidates:
        raise RuntimeError('An eligible installed Qwen3.5 vision artifact is required')
    model = next((m for m in candidates if config['text_models'][m].get('role') == 'coordinator'), candidates[0])
    token = webui('/api/v1/auths/signin', {'email': 'admin@localhost', 'password': ''})['token']
    checks = {}
    left, right = secrets.choice(['red', 'green']), secrets.choice(['blue', 'yellow'])
    image = Image.new('RGB', (640, 320), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 80, 220, 240), fill=left)
    draw.ellipse((410, 80, 570, 240), fill=right)
    raw = io.BytesIO()
    image.save(raw, format='PNG')
    record = upload('acceptance-vision.png', raw.getvalue(), 'image/png', token)
    result = webui('/api/chat/completions', {'model': model, 'stream': False,
        'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Describe the color and shape on the left and on the right. Reply only JSON with left_color, left_shape, right_color, right_shape.'},
            {'type': 'image_url', 'image_url': {'url': record['id']}}]}], 'files': [{'type': 'image', 'id': record['id']}]}, token)
    answer = result['choices'][0]['message']['content']
    try:
        decoded = json.loads(answer[answer.index('{'):answer.rindex('}') + 1])
        checks['ordinary_chat_vision'] = 'passed' if decoded == {'left_color': left, 'left_shape': 'square', 'right_color': right, 'right_shape': 'circle'} else 'failed'
    except (ValueError, KeyError):
        checks['ordinary_chat_vision'] = 'failed'
    code = 'REF ' + secrets.token_hex(3).upper()
    scan = Image.new('RGB', (1100, 300), 'white')
    ImageDraw.Draw(scan).text((50, 85), code, font=ImageFont.load_default(size=76), fill='black')
    raw = io.BytesIO()
    scan.save(raw, format='PDF', resolution=144)
    record = upload('acceptance-scanned.pdf', raw.getvalue(), 'application/pdf', token, process=True)
    checks['native_pdf_upload_processing'] = 'passed' if code in ((record.get('data') or {}).get('content') or '').upper() else 'unverified'
    result = webui('/api/chat/completions', {'model': model, 'stream': False,
        'messages': [{'role': 'user', 'content': 'Read the reference code printed in the attached scanned PDF. Reply with the exact code only.'}],
        'files': [{'type': 'file', 'id': record['id'], 'name': record['filename']}]}, token)
    answer = result['choices'][0]['message']['content']
    checks['ordinary_chat_scanned_pdf'] = 'passed' if code in answer.upper() else 'failed'
    checks.update(physical_login_crash_sleep_wake='pending', native_permission_approval_and_denial='pending',
        browser_to_office_to_live_vault='pending', native_scheduled_execution='pending', target_memory_and_vpn_drop='pending')
    return {'status': 'partial-acceptance', 'model': model, 'checks': checks,
            'notice': 'Only completed checks are evidence. Pending journeys keep this project incomplete.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    try:
        report = run(root)
    except Exception:
        report = {'status': 'failed', 'notice': 'Live acceptance failed. Check service readiness, WebUI attachment setup, installed model capability and Apple OCR. No result is marked passed.'}
    atomic_json(root / 'required-capabilities-acceptance.json', report)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status'] != 'failed' else 1)
