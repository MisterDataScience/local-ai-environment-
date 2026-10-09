"""Transparent stdio relay with compact, unchanged MCP argument schemas."""
import json
import os
import selectors
import subprocess
import sys
from office_setup import TOOLS

DESCRIPTIONS = {
    'office_create': 'Create DOCX/XLSX/PPTX or import Markdown/CSV.',
    'office_read': 'Read outline or scoped content. Prefer bounded reads.',
    'office_query': 'Find canonical element paths using a selector.',
    'office_get': 'Inspect one element by its canonical path.',
    'office_edit': 'Atomic edits; string-valued props. Use help for properties and expect_rev for edits.',
    'office_render': 'Render to HTML/SVG/text; PDF/PNG need a local renderer. Writes output.',
    'office_validate': 'Check OOXML structure. This does not verify visual layout.',
    'office_audit': 'Check accessibility/quality, optionally apply fixes.',
    'office_diff': 'Compare documents or a saved snapshot.',
    'office_template': 'Fill template placeholders with supplied data.',
    'office_convert': 'Convert Office/Markdown/CSV; PDF is output only. Report lossy warnings.',
    'file_snapshot': 'List or restore automatic local pre-edit backups.',
    'office_status': 'Report engine, formats, limits and available renderers.',
    'office_help': 'Read exact syntax. Topics: properties-docx, properties-xlsx, properties-pptx, addressing.',
}


def compact_schema(value):
    if isinstance(value, list):
        return [compact_schema(v) for v in value]
    if isinstance(value, dict):
        return {k: ({name: compact_schema(schema) for name, schema in v.items()}
                    if k in ('properties', '$defs', 'definitions', 'patternProperties') else compact_schema(v))
                for k, v in value.items() if k not in ('description', 'title', 'examples')}
    return value


def compact_response(line):
    message = json.loads(line)
    result = message.get('result')
    if isinstance(result, dict) and isinstance(result.get('tools'), list):
        result['tools'] = [dict(t, description=DESCRIPTIONS[t['name']],
                                inputSchema=compact_schema(t['inputSchema']))
                           for t in result['tools'] if t.get('name') in TOOLS]
    return json.dumps(message, ensure_ascii=False).encode() + b'\n'


def relay(command, env, workspace):
    process = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=sys.stderr)
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin.fileno(), selectors.EVENT_READ, 'client')
    selector.register(process.stdout.fileno(), selectors.EVENT_READ, 'server')
    buffers = {'client': b'', 'server': b''}
    try:
        while process.poll() is None:
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    return
                name = key.data
                buffers[name] += chunk
                if len(buffers[name]) > 8 * 1024 * 1024:
                    raise RuntimeError('Office MCP message exceeds 8 MiB; use a smaller range')
                while b'\n' in buffers[name]:
                    line, buffers[name] = buffers[name].split(b'\n', 1)
                    if not line.strip():
                        continue
                    if name == 'server':
                        sys.stdout.buffer.write(compact_response(line))
                        sys.stdout.buffer.flush()
                    else:
                        process.stdin.write(line + b'\n')
                        process.stdin.flush()
        if process.returncode:
            raise RuntimeError('Office MCP exited with code ' + str(process.returncode))
    finally:
        selector.close()
        process.stdin.close()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
