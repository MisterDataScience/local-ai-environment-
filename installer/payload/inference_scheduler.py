"""Bounded shared text leases and fair exclusive model/mode barriers."""
from contextlib import contextmanager
import threading


class ModelQueue:
    def __init__(self):
        self.condition = threading.Condition()
        self.waiters = []
        self.key = None
        self.active = 0

    @contextmanager
    def lease(self, key=None, slots=1):
        ticket = object()
        with self.condition:
            self.waiters.append((ticket, key))
            try:
                while True:
                    position = next(i for i, item in enumerate(self.waiters) if item[0] is ticket)
                    # A different profile/media/mode barrier prevents later text
                    # readers from overtaking it indefinitely.
                    compatible_prefix = key is not None and all(k == key for _, k in self.waiters[:position])
                    if ((not self.active and position == 0) or
                            (compatible_prefix and self.key == key and self.active < slots)):
                        self.waiters.pop(position)
                        self.key = key
                        self.active += 1
                        self.condition.notify_all()
                        break
                    self.condition.wait()
            except BaseException:
                self.waiters = [w for w in self.waiters if w[0] is not ticket]
                self.condition.notify_all()
                raise
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                if not self.active:
                    self.key = None
                self.condition.notify_all()

    def status(self):
        with self.condition:
            return {'active': self.active, 'waiting': len(self.waiters),
                    'shared_text': self.key is not None}

    @contextmanager
    def idle_lease(self):
        """Maintenance never blocks active/queued work or the audio heartbeat."""
        with self.condition:
            granted = not self.active and not self.waiters
            if granted:
                self.active = 1
                self.key = None
        try:
            yield granted
        finally:
            if granted:
                with self.condition:
                    self.active = 0
                    self.condition.notify_all()
