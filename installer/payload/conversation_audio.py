"""Gateway-owned audio processes and shared/exclusive memory arbitration."""
from contextlib import contextmanager
import json
import os
import selectors
import subprocess
import threading
import time
import speech


class Busy(RuntimeError):
    pass


class Paused(RuntimeError):
    paused = True


class Worker:
    def __init__(self, root, kind):
        folder = root.parent / 'voice-engine'
        env = {k: v for k, v in os.environ.items() if k in {'HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR'}}
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
        self.log = (root / 'logs/conversation-workers.log').open('ab')
        os.chmod(self.log.name, 0o600)
        self.process = subprocess.Popen([str(folder / '.venv/bin/python'), '-u',
            str(root / 'conversation_worker.py'), kind, str(folder)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, env=env, bufsize=0)
        self.buffer = b''
        self.lock = threading.Lock()
        self.ready = False

    def read(self, deadline):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b'\n' not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise RuntimeError('Audio worker timed out')
                block = os.read(self.process.stdout.fileno(), 65536)
                if not block:
                    raise RuntimeError('Audio worker stopped')
                self.buffer += block
                if len(self.buffer) > 4_000_000:
                    raise RuntimeError('Audio worker exceeded its output limit')
        line, self.buffer = self.buffer.split(b'\n', 1)
        return json.loads(line)

    def request(self, data, emit):
        if not self.lock.acquire(blocking=False):
            raise Busy('Audio worker busy')
        try:
            if not self.ready:
                if not self.read(time.monotonic() + 180).get('ready'):
                    raise RuntimeError('Audio worker failed to load')
                self.ready = True
            self.process.stdin.write((json.dumps(data) + '\n').encode())
            self.process.stdin.flush()
            deadline = time.monotonic() + 180
            while True:
                value = self.read(deadline)
                if value.get('error'):
                    raise RuntimeError(value['error'])
                if value.get('done'):
                    return
                emit(value)
        finally:
            self.lock.release()

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
        for pipe in (self.process.stdin, self.process.stdout):
            pipe.close()
        self.log.close()


class Audio:
    def __init__(self, engine):
        self.engine = engine
        self.condition = threading.Condition(threading.RLock())
        self.workers = {}
        self.users = 0
        self.exclusive = False
        self.waiting = 0
        self.enabled = False
        self.last_seen = 0

    def close_workers(self, kinds=('vad', 'stt', 'tts'), suspended=False):
        # Always called under the condition; kill+wait proves memory release.
        for kind in kinds:
            worker = self.workers.get(kind)
            if worker:
                worker.suspended = suspended
                worker.close()
                del self.workers[kind]

    @contextmanager
    def model_job(self, light=False):
        with self.condition:
            if light:
                while self.exclusive or self.waiting:
                    self.condition.wait()
            else:
                self.waiting += 1
                try:
                    # Stop ongoing audio generation before waiting for its reader.
                    self.close_workers(('stt', 'tts'), suspended=True)
                    while self.users or self.exclusive:
                        self.condition.wait()
                    self.exclusive = True
                finally:
                    self.waiting -= 1
                    self.condition.notify_all()
            self.users += 1
        try:
            yield
        finally:
            with self.condition:
                self.users -= 1
                if not light:
                    self.exclusive = False
                self.condition.notify_all()

    def control(self, action):
        with self.condition:
            if action == 'stop':
                self.enabled = False
                self.close_workers()
            elif action == 'cancel':
                if 'tts' in self.workers and self.workers['tts'].lock.locked():
                    self.close_workers(('tts',))
            elif action == 'start':
                if not self.engine.config.get('conversation', {}).get('enabled'):
                    raise RuntimeError('Conversation components missing. Rerun the installer.')
                if self.engine.mode == 'gaming' or self.engine.mode_transitioning or self.engine.mode_error:
                    raise RuntimeError('Conversation requires Normal or Max, ready.')
                self.enabled = True
            elif action != 'heartbeat':
                raise ValueError('Unknown audio control')
            self.last_seen = time.monotonic()
            return {'enabled': self.enabled, 'busy': self.exclusive or bool(self.waiting),
                    'resident': list(self.workers)}

    def expire(self):
        with self.condition:
            if self.enabled and time.monotonic() - self.last_seen > 20:
                self.enabled = False
                self.close_workers()

    def request(self, data, emit):
        kind = {'detect': 'vad', 'transcribe': 'stt', 'speak': 'tts'}.get(data.get('action'))
        if kind is None:
            raise ValueError('Unknown audio request')
        if kind == 'tts':
            payload = speech.request(self.engine.config, self.engine.root, data.get('text'),
                                     {'voice': data.get('voice', 'default'), 'language': 'auto'})
        else:
            pcm = data.get('pcm')
            if not isinstance(pcm, str) or not 0 < len(pcm) <= 1_280_000:
                raise ValueError('Invalid PCM request')
            payload = {'pcm': pcm, 'reset': bool(data.get('reset'))}
        with self.condition:
            if not self.enabled or self.engine.mode == 'gaming' or self.engine.mode_transitioning or self.engine.mode_error:
                raise RuntimeError('Conversation is not active')
            if kind != 'vad' and (self.exclusive or self.waiting):
                raise Paused('Speech paused for specialist or media work')
            if kind != 'vad':
                self.users += 1
            try:
                if kind not in self.workers:
                    self.workers[kind] = Worker(self.engine.root, kind)
                worker = self.workers[kind]
            except BaseException:
                if kind != 'vad':
                    self.users -= 1
                self.condition.notify_all()
                raise
        try:
            worker.request(payload, emit)
        except Busy:
            raise
        except BaseException as error:
            with self.condition:
                if self.workers.get(kind) is worker:
                    self.close_workers((kind,))
            if getattr(worker, 'suspended', False):
                raise Paused('Speech paused for specialist or media work') from error
            raise
        finally:
            with self.condition:
                if kind != 'vad':
                    self.users -= 1
                self.condition.notify_all()
