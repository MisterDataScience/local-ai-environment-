"""Discord lifecycle follows gateway readiness without taking down local chat."""
import logging
import os
import time
from common import launch, stop_process, port_open


class DiscordSupervisor:
    def __init__(self, root, config):
        self.root, self.config = root, config
        self.process = None
        self.epoch = None
        self.retry_at = 0

    def stop(self):
        if self.process:
            stop_process(self.process, timeout=30)
            self.process = None

    def tick(self, status):
        ready = (self.config.get('discord', {}).get('enabled') and status.get('mode') in {'normal', 'max'}
                 and not status.get('transitioning') and not status.get('error'))
        epoch = (status.get('instance_id'), status.get('epoch'), status.get('mode'))
        if not ready or (self.process and self.epoch != epoch):
            self.stop()
        if not ready: return
        if self.process and self.process.poll() is not None:
            self.process = None
            self.retry_at = time.monotonic() + 30
            logging.warning('Discord stopped; retrying in 30 seconds. See logs/discord.log.')
        if self.process or time.monotonic() < self.retry_at: return
        if port_open(4096) or port_open(8003): return
        root = self.root
        self.process = launch([root / 'control/.venv/bin/python', root / 'control/work_agent.py',
                               '--root', root, '--discord'], root / 'control', root / 'logs/discord.log', os.environ.copy())
        self.epoch = epoch
