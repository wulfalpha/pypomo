"""Countdown execution using a monotonic clock."""
import math
import os
import shutil
import sys
import time

from .output import write
from .pretty import Bar, Colors, Pretty, render


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


def run_timer(seconds: int, label: str, *, live: bool = False, pretty: Pretty | None = None,
              finish_line: bool = True, completion: str = 'complete', silent: bool = False) -> None:
    interactive = (live or (sys.stdout is not None and sys.stdout.isatty())) and os.environ.get('TERM') != 'dumb'
    deadline = time.monotonic() + seconds
    settings = (pretty if pretty is not None and pretty.enabled
                else Pretty(bar=Bar(enabled=False), colors=Colors(enabled=False)))

    def display(status: str, remaining: float, *, state: str = 'remaining', final: bool = False) -> None:
        prefix = '\r\033[2K' if interactive else ''
        ending = '\n' if not interactive or (final and (finish_line or state == 'cancelled')) else ''
        text = (render(label, status, remaining, seconds, settings, state,
                       columns=shutil.get_terminal_size().columns)
                if interactive
                else f'{label} · {status}')
        bell = '\a' if final and state == 'complete' and interactive and not silent else ''
        write(f'{prefix}{text}{bell}', end=ending)

    try:
        display(f'{format_duration(seconds)} remaining', seconds)
        last_shown = seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            shown = math.ceil(remaining)
            if interactive and shown != last_shown:
                display(f'{format_duration(shown)} remaining', remaining)
                last_shown = shown
            # Schedule against the deadline, so ordinary oversleep does not accumulate.
            time.sleep(min(remaining, remaining - shown + 1))
    except KeyboardInterrupt:
        remaining = max(0, math.ceil(deadline - time.monotonic()))
        try:
            display(f'cancelled at {format_duration(remaining)} remaining', remaining,
                    state='cancelled', final=True)
        except KeyboardInterrupt:
            pass  # A second cancellation must not escape the CLI as a traceback.
        raise
    display(completion, 0, state='complete', final=True)
