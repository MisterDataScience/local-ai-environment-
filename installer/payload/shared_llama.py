"""Gateway-owned local GGUF server with one model and multiple decode slots."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from backend_http import api, port_open
from tool_protocol import tools_for_ollama, assistant_for_openai


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


class SharedLlama:
    def __init__(self, config):
        self.config = config
        self.process = None
        self.verified = {}
        self.base = 'http://127.0.0.1:11437'

    def files(self):
        result = {}
        for kind in ('binary', 'model', 'mmproj'):
            item = self.config.get('llama', {}).get(kind)
            if item is None and kind == 'mmproj':
                continue
            if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                raise ValueError('Missing local GGUF server artifact: ' + kind)
            path = Path(item['path']).expanduser()
            if not path.is_absolute() or not path.is_file() or path.is_symlink():
                raise ValueError('Select a regular absolute artifact path: ' + kind)
            stat = path.stat()
            signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if self.verified.get(kind) != signature:
                if digest(path) != item.get('sha256'):
                    raise RuntimeError('Shared model artifact changed; configure it again: ' + kind)
                self.verified[kind] = signature
            result[kind] = str(path)
        if not os.access(result['binary'], os.X_OK):
            raise ValueError('Selected llama-server is not executable')
        return result

    def command(self, context, thinking=False):
        files = self.files()
        command = [files['binary'], '--model', files['model'], '--host', '127.0.0.1', '--port', '11437',
                   '--parallel', str(self.config['max_parallel']),
                   '--ctx-size', str(context * self.config['max_parallel']),
                   '--kv-unified-per-slot', str(context),
                   '--alias', 'local-ai-captain', '--jinja', '--cont-batching', '--no-context-shift',
                   '--no-webui', '--chat-template-kwargs', json.dumps({'enable_thinking': thinking})]
        if 'mmproj' in files:
            command += ['--mmproj', files['mmproj']]
        return command

    def start(self, context, thinking=False):
        if self.process and self.process.poll() is None:
            return
        if port_open(11437):
            raise RuntimeError('Shared GGUF port is occupied; no unmanaged server was stopped')
        env = {k: v for k, v in os.environ.items() if k in {'HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR'}}
        # Inherit the gateway process group so supervisor stop also stops this
        # server. No arbitrary argv, credentials or network tools are inherited.
        self.process = subprocess.Popen(self.command(context, thinking), env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Local GGUF server failed to load the selected model; verify binary/model compatibility')
            try:
                api(self.base, '/health', timeout=2)
                return
            except (URLError, TimeoutError, OSError, RuntimeError):
                time.sleep(0.5)
        self.stop()
        raise RuntimeError('Shared GGUF server startup exceeded five minutes')

    def stop(self):
        if self.process is None:
            return
        process = self.process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
        process.wait(timeout=15)
        if port_open(11437):
            raise RuntimeError('Shared GGUF server did not release its port')
        self.process = None

    def chat(self, body, limit):
        tools = tools_for_ollama(body)
        payload = {'model': 'local-ai-captain', 'messages': body['messages'], 'stream': False,
                   'max_tokens': limit, 'cache_prompt': True}
        if tools:
            payload['tools'] = tools
        if isinstance(body.get('temperature'), (int, float)):
            payload['temperature'] = body['temperature']
        response = api(self.base, '/v1/chat/completions', payload, timeout=1800)
        choices = response.get('choices')
        if not isinstance(choices, list) or not choices:
            raise RuntimeError('Local GGUF server returned no completion')
        choice = choices[0]
        result = assistant_for_openai(choice['message'], tools)
        body['_finish_reason'] = choice.get('finish_reason', 'stop')
        usage = response.get('usage', {})
        if all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('prompt_tokens', 'completion_tokens')):
            body['_usage'] = {'prompt_tokens': usage['prompt_tokens'], 'completion_tokens': usage['completion_tokens'],
                              'total_tokens': usage['prompt_tokens'] + usage['completion_tokens']}
        return result
