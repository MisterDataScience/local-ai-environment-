"""Bounded token delivery. The executor retains ownership through cancellation."""
import json
import queue
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from backend_http import ContextLengthError


class Stream:
    def __init__(self):
        self.events = queue.Queue(64)
        self.cancelled = threading.Event()

    def send(self, delta):
        while not self.cancelled.is_set():
            try:
                self.events.put(delta, timeout=.2)
                return
            except queue.Full:
                pass
        raise RuntimeError('Response cancelled')


def chat(base, payload, stream):
    payload = dict(payload, stream=True)
    request = Request(base + '/api/chat', data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'})
    message = {'role': 'assistant', 'content': '', 'thinking': '', 'tool_calls': []}
    done = None
    try:
        with urlopen(request, timeout=1800) as response:
            for line in response:
                if stream.cancelled.is_set():
                    raise RuntimeError('Response cancelled')
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get('error'):
                    raise RuntimeError(str(event['error']))
                part = event.get('message', {})
                for key in ('content', 'thinking'):
                    value = part.get(key, '')
                    if not isinstance(value, str):
                        raise RuntimeError('Invalid streamed text')
                    message[key] += value
                    if value and key == 'content':
                        stream.send({'content': value})
                # Ollama supplies complete structured calls. Validate and emit once,
                # after the stream completes, to preserve stable call IDs.
                message['tool_calls'].extend(part.get('tool_calls', []))
                if len(message['tool_calls']) > 32:
                    raise RuntimeError('Too many tool calls')
                if event.get('done'):
                    done = event
                    break
    except HTTPError as error:
        detail = error.read(8192).decode(errors='replace')
        if error.code in (400, 413) and any(p in detail.lower() for p in (
                'context length', 'context window', 'context size', 'prompt is too long', 'input length exceeds')):
            raise ContextLengthError('Backend rejected context length') from error
        raise RuntimeError('Streaming backend rejected request: ' + detail) from error
    if done is None:
        raise RuntimeError('Backend stream ended without a completion marker')
    return dict(done, message=message)
