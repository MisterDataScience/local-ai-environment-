"""Gateway-owned local GGUF server with one model and multiple decode slots."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from backend_http import api, port_open
from tool_protocol import tools_for_ollama, assistant_for_openai, messages_for_ollama


def openai_messages(original, cleaned):
    """Send validated text/pixels while retaining native call/result identities."""
    result = []
    for source, message in zip(original, cleaned):
        item = {'role': message['role'], 'content': message['content']}
        if message.get('images'):
            item['content'] = [{'type': 'text', 'text': message['content']}, *[
                {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + image}}
                for image in message['images']]]
        if message['role'] == 'tool':
            item['tool_call_id'] = source['tool_call_id']
        if message.get('tool_calls'):
            item['tool_calls'] = [{'id': call['id'], 'type': 'function', 'function': {
                'name': clean['function']['name'],
                'arguments': json.dumps(clean['function']['arguments'], ensure_ascii=False)}}
                for call, clean in zip(source['tool_calls'], message['tool_calls'])]
        if 'thinking' in message:
            item['reasoning_content'] = message['thinking']
        result.append(item)
    return result


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


class SharedLlama:
    def __init__(self, config, log_path=None):
        self.config = config
        self.process = None
        self.running_slots = None
        self.log_path = Path(log_path) if log_path is not None else None
        self.verified = {}
        self.base = 'http://127.0.0.1:11437'

    def files(self):
        result = {}
        for kind in ('binary', 'model', 'mmproj', 'lora'):
            item = self.config.get('llama', {}).get(kind)
            if item is None and kind == 'mmproj':
                continue
            if item is None and kind == 'lora' and self.config.get('variant') != 'atomicchat-uncensored-lora':
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

    def slots(self, parallel):
        slots = self.config['max_parallel'] if parallel is None else parallel
        if type(slots) is not int or not 1 <= slots <= self.config['max_parallel']:
            raise ValueError('Shared GGUF parallel slots must be within the configured Captain limit')
        return slots

    def command(self, context, thinking=False, parallel=None):
        slots = self.slots(parallel)
        files = self.files()
        command = [files['binary'], '--model', files['model'], '--host', '127.0.0.1', '--port', '11437',
                   '--parallel', str(slots),
                   '--ctx-size', str(context * slots),
                   '--kv-unified-per-slot', str(context),
                   '--alias', 'local-ai-captain', '--jinja', '--cont-batching', '--no-context-shift',
                   '--no-webui', '--chat-template-kwargs', json.dumps({'enable_thinking': thinking})]
        if 'mmproj' in files:
            command += ['--mmproj', files['mmproj']]
        if 'lora' in files:
            # Static LoRA at the default scale 1.0 is applied to all decode
            # slots, so the captain and every delegated worker use the variant.
            command += ['--lora', files['lora']]
        return command

    def start(self, context, thinking=False, parallel=None):
        slots = self.slots(parallel)
        if self.process and self.process.poll() is None:
            if self.running_slots != slots:
                raise RuntimeError('Running shared GGUF slot count differs from requested resource mode')
            return
        if port_open(11437):
            raise RuntimeError('Shared GGUF port is occupied; no unmanaged server was stopped')
        env = {k: v for k, v in os.environ.items() if k in {'HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR'}}
        # Inherit the gateway process group so supervisor stop also stops this
        # server. No arbitrary argv, credentials or network tools are inherited.
        command = self.command(context, thinking, slots)
        if self.log_path is None:
            self.process = subprocess.Popen(command, env=env,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Keep native model-loading errors available without weakening file privacy.
            self.log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(self.log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'ab') as log:
                self.process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        self.running_slots = slots
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Local GGUF server failed to load the selected model; '
                                   'check control/logs/shared-llama.log for backend errors')
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
        self.running_slots = None

    def chat(self, body, limit, messages=None, transport=None):
        tools = tools_for_ollama(body)
        cleaned = messages if messages is not None else messages_for_ollama(body['messages'])
        payload = {'model': 'local-ai-captain', 'messages': openai_messages(body['messages'], cleaned), 'stream': False,
                   'max_tokens': limit, 'cache_prompt': True}
        if tools:
            payload['tools'] = tools
        if isinstance(body.get('temperature'), (int, float)):
            payload['temperature'] = body['temperature']
        response = (transport or api)(self.base, '/v1/chat/completions', payload, timeout=1800)
        usage = response.get('usage') if isinstance(response.get('usage'), dict) else {}
        body['_accounting_usage'] = {k: usage.get(k) for k in ('prompt_tokens', 'completion_tokens')}
        choices = response.get('choices')
        if not isinstance(choices, list) or not choices:
            raise RuntimeError('Local GGUF server returned no completion')
        choice = choices[0]
        message = dict(choice['message'])
        if 'reasoning_content' in message:
            message['thinking'] = message['reasoning_content']
        result = assistant_for_openai(message, tools)
        if isinstance(result, dict) and result.get('tool_calls'):
            seen = set()
            for call, native in zip(result['tool_calls'], message['tool_calls']):
                identifier = native.get('id')
                if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200 or identifier in seen:
                    raise RuntimeError('Local GGUF server returned invalid or duplicate tool call IDs')
                seen.add(identifier)
                call['id'] = identifier
        body['_finish_reason'] = choice.get('finish_reason', 'stop')
        if all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('prompt_tokens', 'completion_tokens')):
            body['_usage'] = {'prompt_tokens': usage['prompt_tokens'], 'completion_tokens': usage['completion_tokens'],
                              'total_tokens': usage['prompt_tokens'] + usage['completion_tokens']}
        return result
