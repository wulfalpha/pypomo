"""Scoped cancellation handlers for CLI invocations."""
import signal
import threading
from contextlib import contextmanager


class Terminated(KeyboardInterrupt):
    def __init__(self, signum: int):
        self.signum = signum


def _terminate(signum, frame):
    raise Terminated(signum)


@contextmanager
def cancellation_handlers():
    previous = {}
    try:
        if threading.current_thread() is threading.main_thread():
            for name in ('SIGTERM', 'SIGHUP'):
                signum = getattr(signal, name, None)
                if signum is not None:
                    previous[signum] = signal.signal(signum, _terminate)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
