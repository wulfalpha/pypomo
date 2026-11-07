"""Shared test helpers: keyboard isolation, fake clocks, and subprocess runners."""
import contextlib
import io
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from pypomo import cli
from pypomo.timer import run_timer

# Directory containing the imported pypomo package (src/ or site-packages), so
# subprocesses run the same code as the in-process tests.
SRC = Path(cli.__file__).resolve().parents[1]
PY = sys.executable
POSIX = os.name == 'posix'
EMPTY_HOME = tempfile.TemporaryDirectory()


def disable_keyboard():
    """Keep unit tests independent of whether stdin is a terminal.

    Use as a module's `setUpModule`. Real key handling is covered by PTY tests.
    """
    patcher = patch('pypomo.cli.keyboard', lambda: nullcontext(None))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class FakeClock:
    """Monotonic clock where every sleep(x) advances by x + oversleep."""

    def __init__(self, oversleep=0.0, start=1000.0):
        self.now = start
        self.oversleep = oversleep

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0, f'sleep called with non-positive {seconds}'
        self.now += seconds + self.oversleep


class FakeKeys:
    """Delivers scripted keypresses at fixed fake-clock times."""

    def __init__(self, clock, events):
        self.clock = clock
        self.events = sorted((clock.now + at, key) for at, key in events)

    def read(self, timeout):
        if self.events and (timeout is None or self.events[0][0] <= self.clock.now + timeout):
            at, key = self.events.pop(0)
            self.clock.now = max(self.clock.now, at)
            if key is KeyboardInterrupt:
                raise KeyboardInterrupt
            return key
        if timeout is None:
            raise AssertionError('blocked waiting for a key that never arrives')
        self.clock.now += timeout
        return None


def cli_env(env_extra=None):
    """Environment that runs this pypomo with an empty, isolated config location."""
    env = dict(os.environ, PYTHONPATH=str(SRC), HOME=EMPTY_HOME.name,
               XDG_CONFIG_HOME=EMPTY_HOME.name, PYTHONUTF8='1')
    env.pop('PYTHONIOENCODING', None)
    env.update(env_extra or {})
    return env


def _default_sigint():
    # Children of a backgrounded shell inherit SIGINT=SIG_IGN; restore it for signal tests.
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def run_cli(*args, env_extra=None, **kw):
    """Run pypomo in a subprocess with an empty config dir."""
    return subprocess.run([PY, '-m', 'pypomo', *args], capture_output=True, encoding='utf-8', errors='replace',
                          env=cli_env(env_extra), timeout=30, **kw)


def run_fake(seconds, oversleep=0.0, **kw):
    clock = FakeClock(oversleep)
    out = io.StringIO()
    with patch('pypomo.timer.time.monotonic', clock.monotonic), \
         patch('pypomo.timer.time.sleep', clock.sleep), contextlib.redirect_stdout(out):
        run_timer(seconds, 'edge', **kw)
    return out.getvalue(), clock


def shown_seconds(text):
    values = []
    for h, m, s in re.findall(r'(\d+):(\d\d):(\d\d) remaining', text):
        values.append(int(h) * 3600 + int(m) * 60 + int(s))
    return values


def spawn(*args, env_extra=None):
    """Start pypomo (stdout+stderr merged) and wait until its first status line is printed."""
    proc = subprocess.Popen([PY, '-m', 'pypomo', *args], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, encoding='utf-8', errors='replace', env=cli_env(env_extra),
                            preexec_fn=_default_sigint)
    data = b''
    deadline = time.monotonic() + 5
    try:
        while b'\n' not in data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([proc.stdout], [], [], remaining)[0]:
                raise subprocess.TimeoutExpired(proc.args, 5)
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                raise RuntimeError('Timer exited before its first status line')
            data += chunk
    except BaseException:
        proc.kill()
        proc.communicate()
        raise
    proc.first_line = data.decode('utf-8', 'replace')
    return proc


def finish(proc, timeout=20):
    """Return everything the process printed, after it exits."""
    try:
        rest, _ = proc.communicate(timeout=timeout)
        return proc.first_line + rest
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
