"""Single-key terminal input for pause/resume and phase confirmation."""
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

PAUSE_KEYS = frozenset('p ')
QUIT_KEYS = frozenset('q')
ENTER_KEYS = frozenset('\r\n')


class Keyboard:
    """Reads keys without waiting for Enter. Created only by `keyboard()`."""

    def read(self, timeout: float | None) -> str | None:
        """Return one keypress, or None when `timeout` seconds pass first.

        Escape sequences (arrow and function keys) are discarded.
        """
        raise NotImplementedError


class _PosixKeyboard(Keyboard):
    def __init__(self, fd: int):
        self.fd = fd

    def read(self, timeout: float | None) -> str | None:
        import select

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            wait = None if deadline is None else max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([self.fd], [], [], wait)
            if not ready:
                return None
            data = os.read(self.fd, 64).decode(errors='ignore')
            if not data:  # Terminal hung up; behave as if no key will ever arrive.
                if timeout is not None:
                    time.sleep(wait or 0)
                    return None
                raise KeyboardInterrupt
            if not data.startswith('\x1b'):
                return data[0]


class _WindowsKeyboard(Keyboard):
    def read(self, timeout: float | None) -> str | None:
        import msvcrt

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            while msvcrt.kbhit():
                key = msvcrt.getwch()
                if key in ('\x00', '\xe0'):  # Prefix of an arrow or function key.
                    msvcrt.getwch()
                    continue
                if key == '\x03':
                    raise KeyboardInterrupt
                return key
            if deadline is not None and time.monotonic() >= deadline:
                return None
            remaining = 0.05 if deadline is None else deadline - time.monotonic()
            time.sleep(max(0.0, min(0.05, remaining)))


def _foreground_tty(stream: TextIO) -> int | None:
    try:
        fd = stream.fileno()
        if not os.isatty(fd):
            return None
    except (AttributeError, OSError, ValueError):
        return None
    try:
        # A background job that changes terminal modes is stopped with SIGTTOU.
        if os.tcgetpgrp(fd) != os.getpgrp():
            return None
    except (AttributeError, OSError):
        pass  # Windows, or a terminal that is not our controlling terminal.
    return fd


@contextmanager
def keyboard() -> Iterator[Keyboard | None]:
    """Yield a Keyboard when stdin is a foreground terminal, else None.

    On POSIX the terminal is switched to cbreak mode (no line buffering, no
    echo) and restored on exit. Ctrl+C and Ctrl+Z keep their usual meaning.
    """
    fd = None if sys.stdin is None else _foreground_tty(sys.stdin)
    if fd is None:
        yield None
        return
    if sys.platform == 'win32':
        yield _WindowsKeyboard()
        return
    import signal
    import termios
    import threading
    import tty

    def cbreak(*_):
        try:
            tty.setcbreak(fd, termios.TCSANOW)
        except termios.error:
            pass

    try:
        saved = termios.tcgetattr(fd)
        tty.setcbreak(fd, termios.TCSANOW)
    except termios.error:
        yield None
        return
    previous = None
    if threading.current_thread() is threading.main_thread():
        # The shell may restore its own terminal modes after Ctrl+Z; reapply ours on `fg`.
        previous = signal.signal(signal.SIGCONT, cbreak)
    try:
        yield _PosixKeyboard(fd)
    finally:
        if previous is not None:
            signal.signal(signal.SIGCONT, previous)
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        except termios.error:
            pass
