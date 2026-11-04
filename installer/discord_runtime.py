"""Discord lifecycle follows gateway readiness without taking down local chat."""
import logging
import os
import json
import subprocess
import threading
import time
from common import launch, stop_process, port_open


class DiscordSupervisor:
    def __init__(self, root, config):
        self.root, self.config = root, config
        self.process = None
        self.bridge = None
        self.epoch = None
        self.retry_at = 0

    def stop(self):
        if self.process:
            stop_process(self.process, timeout=30)
            self.process = None
        if self.bridge:
            close_bridge(self.bridge)
            self.bridge = None

    def tick(self, status):
        ready = (self.config.get('discord', {}).get('enabled') and status.get('mode') in {'normal', 'max'}
                 and not status.get('transitioning') and not status.get('error'))
        epoch = (status.get('instance_id'), status.get('epoch'), status.get('mode'))
        if not ready or (self.process and self.epoch != epoch):
            self.stop()
        if not ready: return
        if self.process and self.process.poll() is not None:
            self.process = None
            if self.bridge:
                close_bridge(self.bridge)
                self.bridge = None
            self.retry_at = time.monotonic() + 30
            logging.warning('Discord stopped; retrying in 30 seconds. See logs/discord.log.')
        if self.process or time.monotonic() < self.retry_at: return
        if port_open(8003): return
        root = self.root
        if port_open(4096):
            # Reuse only our authenticated, verified managed Captain. A second
            # OpenCode process cannot bind its port while core chat is running.
            from managed_captain import agent_status, credentials, READY_NAME
            if not (root / 'control' / READY_NAME).is_file(): return
            try:
                agent_status(root, timeout=3)
                from conversation import launch as conversation_bridge
                self.bridge, _ = conversation_bridge(root, credentials(root)['password'], self.config)
                self.process = start_adapter(root, self.config, self.bridge.app.key)
                self.epoch = epoch
            except Exception:
                self.stop()
                self.retry_at = time.monotonic() + 30
                logging.warning('Discord bridge unavailable; local Captain remains running.')
            return
        self.process = launch([root / 'control/.venv/bin/python', root / 'control/work_agent.py',
                               '--root', root, '--discord'], root / 'control', root / 'logs/discord.log', os.environ.copy())
        self.epoch = epoch


def close_bridge(server):
    server.app.closed.set()
    def release():
        try:
            server.app.stop()
        except Exception:
            pass
    cleanup = threading.Thread(target=release, daemon=True)
    cleanup.start()
    cleanup.join(timeout=2)
    server.shutdown()
    server.server_close()


def start_adapter(root, config, bridge_key, *, acceptance=False):
    from discord_setup import read_token, NODE_VERSION
    settings = config['discord']
    token = read_token(root, settings['application_id'])
    env = {k: v for k, v in os.environ.items() if k in {'HOME', 'PATH', 'TMPDIR', 'LANG'}}
    with (root / 'logs/discord.log').open('ab') as log:
        process = subprocess.Popen([str(root / 'tools/node' / NODE_VERSION / 'bin/node'),
            str(root / 'discord-engine/discord-adapter.mjs')], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if acceptance else log, stderr=log, env=env,
            cwd=root / 'discord-engine', start_new_session=True, text=True)
    try:
        process.stdin.write(json.dumps({'token': token, 'config': settings,
            'bridgeKey': bridge_key, 'acceptance': acceptance}))
        process.stdin.close()
    except BaseException:
        stop_process(process, timeout=30)
        raise
    return process
