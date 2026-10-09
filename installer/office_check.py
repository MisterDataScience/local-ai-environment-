"""Real MCP acceptance for all formats, run by setup and Check Office.command."""
import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile


class Client:
    def __init__(self, command, env, workspace):
        self.process = subprocess.Popen(command, env=env, cwd=workspace, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b''
        self.sequence = 0

    def send(self, value):
        self.process.stdin.write(json.dumps(value).encode() + b'\n')
        self.process.stdin.flush()

    def request(self, method, params):
        self.sequence += 1
        self.send(dict(jsonrpc='2.0', id=self.sequence, method=method, params=params))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if b'\n' not in self.buffer:
                if not self.selector.select(timeout=0.2):
                    if self.process.poll() is not None:
                        raise RuntimeError('Office MCP exited: ' + self.process.stderr.read(4096).decode(errors='replace'))
                    continue
                block = os.read(self.process.stdout.fileno(), 65536)
                if not block:
                    raise RuntimeError('Office MCP closed stdout')
                self.buffer += block
                if len(self.buffer) > 8 * 1024 * 1024:
                    raise RuntimeError('Office acceptance result too large')
                continue
            line, self.buffer = self.buffer.split(b'\n', 1)
            response = json.loads(line)
            if response.get('id') == self.sequence:
                if 'error' in response:
                    raise RuntimeError(str(response['error']))
                return response['result']
        raise TimeoutError('Office MCP timed out; no automatic retry')

    def call(self, name, args, expected_error=None):
        result = self.request('tools/call', {'name': name, 'arguments': args})
        texts = [c['text'] for c in result.get('content', []) if c.get('type') == 'text']
        envelope = json.loads(texts[0]) if texts else result.get('structuredContent', {})
        if expected_error:
            if envelope.get('ok') is not False or envelope.get('error', {}).get('code') != expected_error:
                raise RuntimeError(f'{name}: expected {expected_error}, got {envelope}')
        elif result.get('isError') or envelope.get('ok') is not True:
            raise RuntimeError(f'{name}: {envelope}')
        return envelope

    def close(self):
        self.selector.close()
        self.process.stdin.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()
        self.process.stderr.close()


def rss_kib(pid):
    try:
        return int(subprocess.check_output(['/bin/ps', '-o', 'rss=', '-p', str(pid)], timeout=2).strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def verify_network_policy():
    from office_setup import NETWORK_POLICY, engine_environment
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        server.listen(2)
        port = server.getsockname()[1]
        with socket.create_connection(('127.0.0.1', port), timeout=2):
            pass
        code = ('import socket,sys,errno\n'
                'try:\n socket.create_connection(("127.0.0.1", int(sys.argv[1])),timeout=2)\n'
                'except OSError as e:\n sys.exit(0 if e.errno in (errno.EPERM,errno.EACCES) else 2)\n'
                'sys.exit(1)\n')
        subprocess.run(['/usr/bin/sandbox-exec', '-p', NETWORK_POLICY, sys.executable,
                        '-c', code, str(port)], check=True, timeout=10, env=engine_environment())


def check(root, command, env):
    from office_setup import TOOLS, VERSION
    logs = root / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix='office-check-', dir=logs)).resolve()
    command = list(command)
    # Both production and test commands end with --workspace <directory>.
    if command[-2] != '--workspace':
        raise ValueError('Missing explicit Office workspace')
    command[-1] = str(workspace)
    report = {'version': VERSION, 'platform': sys.platform, 'workspace': str(workspace),
              'status': 'running', 'checks': [], 'samples_rss_kib': [],
              'visual_review': 'not performed', 'local_model_routing': 'not performed',
              'memory_scope': 'Launched command RSS sampled at 100ms; excludes descendants and model processes'}
    client = None
    stop = threading.Event()
    sampler = None
    try:
        if sys.platform == 'darwin':
            if command[0] != '/usr/bin/sandbox-exec':
                raise RuntimeError('Mac acceptance must run with network denial')
            verify_network_policy()
            report['network_policy'] = 'network denied; live loopback denial test passed'
        else:
            report['network_policy'] = 'not tested on macOS'
        client = Client(command, env, workspace)
        def sample():
            while not stop.is_set():
                value = rss_kib(client.process.pid)
                if value is not None:
                    report['samples_rss_kib'].append(value)
                stop.wait(0.1)
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        init = client.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                              'clientInfo': {'name': 'local-ai-office-check', 'version': '1'}})
        if init['serverInfo']['version'] != VERSION:
            raise RuntimeError('Unexpected AIOffice MCP version')
        client.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        available = client.request('tools/list', {})['tools']
        report['tools'] = [t['name'] for t in available]
        if not set(TOOLS).issubset(report['tools']):
            raise RuntimeError('Required Office MCP tools missing')
        report['idle_rss_kib'] = rss_kib(client.process.pid)
        report['doctor'] = client.call('office_status', {})['data']
        call = client.call
        (workspace / 'source.md').write_text('# Office acceptance\n\nOriginal paragraph.\n\n| Item | Value |\n| --- | --- |\n| Test | 42 |\n')
        call('office_create', {'file': 'report.docx', 'from': 'source.md'})
        original = call('office_read', {'file': 'report.docx', 'view': 'text', 'max_bytes': 8000})
        if 'Original paragraph' not in json.dumps(original):
            raise RuntimeError('DOCX import readback failed')
        call('office_edit', {'file': 'report.docx', 'expect_rev': original['meta']['rev'], 'ops': [
            {'op': 'replace', 'path': '/', 'props': {'find': 'Original paragraph', 'replace': 'Edited paragraph'}}]})
        if 'Edited paragraph' not in json.dumps(call('office_read', {'file': 'report.docx', 'view': 'text'})):
            raise RuntimeError('DOCX edit readback failed')
        call('office_create', {'file': 'book.xlsx'})
        call('office_edit', {'file': 'book.xlsx', 'ops': [
            {'op': 'set', 'path': '/Sheet1/' + cell, 'props': {'value': value}}
            for cell, value in [('A1', '20'), ('A2', '22'), ('A3', '=SUM(A1:A2)')]]})
        total = call('office_get', {'file': 'book.xlsx', 'path': '/Sheet1/A3'})
        report['formula_readback'] = total['data']
        call('office_create', {'file': 'deck.pptx', 'title': 'Office acceptance'})
        call('office_edit', {'file': 'deck.pptx', 'ops': [
            {'op': 'add', 'path': '/slide[1]', 'type': 'slide', 'position': 'after', 'props': {'title': 'Checks'}},
            {'op': 'add', 'path': '/slide[2]', 'type': 'shape', 'props': {'text': '• Create\n• Read\n• Edit',
             'x': '2cm', 'y': '4cm', 'w': '18cm', 'h': '5cm'}}]})
        call('office_edit', {'file': 'deck.pptx', 'ops': [
            {'op': 'replace', 'path': '/', 'props': {'find': 'Checks', 'replace': 'Passed checks'}}]})
        for name in ('report.docx', 'book.xlsx', 'deck.pptx'):
            result = call('office_validate', {'file': name})
            if result['data'].get('valid') is not True:
                raise RuntimeError(f'{name}: invalid OOXML: {result}')
            call('office_read', {'file': name, 'view': 'text', 'max_bytes': 8000})
            report['checks'].append(name + ': create/read/edit/validate')
        # Independently inspect generated OOXML, not only the producer's success flag.
        with zipfile.ZipFile(workspace / 'report.docx') as z:
            xml = ET.fromstring(z.read('word/document.xml'))
            if not xml.findall('.//{*}tbl') or 'Edited paragraph' not in ''.join(xml.itertext()):
                raise RuntimeError('DOCX table/content missing')
        with zipfile.ZipFile(workspace / 'book.xlsx') as z:
            xml = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            cell = next(c for c in xml.findall('.//{*}c') if c.attrib.get('r') == 'A3')
            if cell.find('{*}f').text != 'SUM(A1:A2)' or float(cell.find('{*}v').text) != 42:
                raise RuntimeError('XLSX formula or cached result incorrect')
        with zipfile.ZipFile(workspace / 'deck.pptx') as z:
            xml = ET.fromstring(z.read('ppt/slides/slide2.xml'))
            if 'Passed checks' not in ''.join(xml.itertext()):
                raise RuntimeError('PPTX slide edit missing')
        report['checks'].append('independent OOXML content and formula-cache inspection')
        for name, output, kind in [('report.docx', 'report.html', 'html'), ('book.xlsx', 'book.html', 'html'),
                                   ('deck.pptx', 'slide.svg', 'svg')]:
            call('office_render', {'file': name, 'to': kind, 'output': output,
                                  **({'scope': '/slide[2]'} if kind == 'svg' else {})})
            if not (workspace / output).is_file():
                raise RuntimeError('Rendered output missing: ' + output)
        report['checks'].append('DOCX/XLSX HTML and PPTX SVG rendering')
        call('office_create', {'file': '../escape.docx'}, expected_error='sandbox_denied')
        (workspace / 'escape').symlink_to(logs.resolve(), target_is_directory=True)
        call('office_create', {'file': 'escape/escape.docx'}, expected_error='sandbox_denied')
        report['checks'].append('parent traversal and symlink escape rejected')
        snaps = call('file_snapshot', {'file': 'report.docx', 'action': 'list'})
        report['snapshots'] = snaps['data']
        call('office_edit', {'file': 'report.docx', 'expect_rev': '000000000000', 'ops': [
            {'op': 'replace', 'path': '/', 'props': {'find': 'Edited', 'replace': 'Wrong'}}]}, expected_error='stale_address')
        report['checks'].append('snapshots listed and stale revision rejected')
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        stop.set()
        if sampler:
            sampler.join(timeout=3)
        if client:
            client.close()
        report['sampled_peak_rss_kib'] = max(report['samples_rss_kib'], default=None)
        (workspace / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (logs / 'office-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
