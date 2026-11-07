"""Countdown execution using a monotonic clock."""
import math
import os
import shutil
import sys
import time

from .hooks import EventHandler
from .keys import ENTER_KEYS, PAUSE_KEYS, QUIT_KEYS, Keyboard
from .output import write
from .pretty import Bar, Colors, Pretty, render


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


class Screen:
    """Draws one timer's status as an in-place line or as plain lines."""

    def __init__(self, label: str, total: int, *, live: bool, pretty: Pretty | None,
                 silent: bool, finish_line: bool):
        self.label, self.total = label, total
        self.silent, self.finish_line = silent, finish_line
        self.interactive = ((live or (sys.stdout is not None and sys.stdout.isatty()))
                            and os.environ.get('TERM') != 'dumb')
        self.settings = (pretty if pretty is not None and pretty.enabled
                         else Pretty(bar=Bar(enabled=False), colors=Colors(enabled=False)))

    def show(self, status: str, remaining: float, *, state: str = 'remaining', final: bool = False) -> None:
        interactive = self.interactive
        prefix = '\r\033[2K' if interactive else ''
        ending = '\n' if not interactive or (final and (self.finish_line or state == 'cancelled')) else ''
        text = (render(self.label, status, remaining, self.total, self.settings, state,
                       columns=shutil.get_terminal_size().columns)
                if interactive
                else f'{self.label} · {status}')
        bell = '\a' if final and state == 'complete' and interactive and not self.silent else ''
        write(f'{prefix}{text}{bell}', end=ending)

    def cancelled(self, status: str, remaining: float) -> None:
        try:
            self.show(status, remaining, state='cancelled', final=True)
        except KeyboardInterrupt:
            pass  # A second cancellation must not escape the CLI as a traceback.


def _wait_for(keys: Keyboard, wanted: frozenset[str]) -> None:
    """Block until a key in `wanted` is pressed; a quit key cancels."""
    while True:
        key = keys.read(None)
        if key in QUIT_KEYS:
            raise KeyboardInterrupt
        if key in wanted:
            return


def run_timer(seconds: int, label: str, *, live: bool = False, pretty: Pretty | None = None,
              finish_line: bool = True, completion: str = 'complete', silent: bool = False,
              keys: Keyboard | None = None, on_event: EventHandler | None = None) -> None:
    """Count down `seconds`. With `keys`, p/space pauses and resumes, q cancels.

    `on_event(name, remaining)` is called for start, pause, resume, cancel and end.
    """
    def emit(event: str, remaining: int) -> None:
        if on_event is not None:
            on_event(event, remaining)

    screen = Screen(label, seconds, live=live, pretty=pretty, silent=silent, finish_line=finish_line)
    deadline = time.monotonic() + seconds
    paused: float | None = None  # Remaining seconds while paused.
    try:
        screen.show(f'{format_duration(seconds)} remaining', seconds)
        emit('start', seconds)
        last_shown: int | None = seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            shown = math.ceil(remaining)
            if screen.interactive and shown != last_shown:
                screen.show(f'{format_duration(shown)} remaining', remaining)
                last_shown = shown
            # Schedule against the deadline, so ordinary oversleep does not accumulate.
            delay = min(remaining, remaining - shown + 1)
            if keys is None:
                time.sleep(delay)
                continue
            key = keys.read(delay)
            if key in QUIT_KEYS:
                raise KeyboardInterrupt
            if key in PAUSE_KEYS:
                paused = max(0.0, deadline - time.monotonic())
                text = format_duration(math.ceil(paused))
                screen.show(f'paused at {text} remaining · press p to resume', paused, state='paused')
                emit('pause', math.ceil(paused))
                _wait_for(keys, PAUSE_KEYS)
                if not screen.interactive:
                    screen.show(f'resumed at {text} remaining', paused)
                emit('resume', math.ceil(paused))
                deadline = time.monotonic() + paused
                paused, last_shown = None, None
    except KeyboardInterrupt:
        if paused is not None:
            remaining = math.ceil(paused)
        else:
            remaining = max(0, math.ceil(deadline - time.monotonic()))
        screen.cancelled(f'cancelled at {format_duration(remaining)} remaining', remaining)
        try:
            emit('cancel', remaining)
        except KeyboardInterrupt:
            pass
        raise
    screen.show(completion, 0, state='complete', final=True)
    emit('end', 0)


def wait_for_start(seconds: int, label: str, *, live: bool = False, pretty: Pretty | None = None,
                   keys: Keyboard | None = None) -> None:
    """Show a ready line and wait for Enter before a phase starts.

    Without a keyboard, a line is read from stdin; a closed or exhausted stdin
    starts the phase immediately, so unattended runs never block forever.
    """
    if keys is None and sys.stdin is None:
        return
    screen = Screen(label, seconds, live=live, pretty=pretty, silent=True, finish_line=False)
    try:
        screen.show('ready · press Enter to start', seconds, state='paused')
        if keys is not None:
            _wait_for(keys, ENTER_KEYS)
        else:
            try:
                sys.stdin.readline()
            except (OSError, ValueError):
                pass
    except KeyboardInterrupt:
        screen.cancelled('cancelled before start', seconds)
        raise
