"""Shared test setup."""
import unittest
from contextlib import nullcontext
from unittest.mock import patch


def disable_keyboard():
    """Keep unit tests independent of whether stdin is a terminal.

    Use as a module's `setUpModule`. Real key handling is covered by PTY tests.
    """
    patcher = patch('pypomo.cli.keyboard', lambda: nullcontext(None))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


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
