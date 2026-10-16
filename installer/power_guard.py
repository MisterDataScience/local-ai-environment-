"""Non-privileged, process-bound idle-sleep prevention for the headless Mac.

caffeinate -i -s prevents *idle* system sleep while LOCAL AI's supervisor
runs. It doesn't disable display sleep, prevent intentional sleep/shutdown,
change pmset settings, or claim to boot through FileVault's login window.
"""
import os
import subprocess


def begin():
    return subprocess.Popen(
        ['/usr/bin/caffeinate', '-i', '-s', '-w', str(os.getpid())],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)


def maintain(process):
    """Reacquire the idle-sleep assertion if caffeinate was terminated."""
    if process is None or process.poll() is not None:
        return begin()
    return process


def finish(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
