"""Countdown execution using a monotonic clock."""
import math
import sys
import time

from .pretty import Pretty, render


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


def run_timer(seconds: int, label: str, *, live: bool = False, pretty: Pretty | None = None,
              finish_line: bool = True, completion: str = 'complete') -> None:
    interactive = live or sys.stdout.isatty()
    deadline = time.monotonic() + seconds

    def display(status: str, remaining: float, *, state: str = 'remaining', final: bool = False) -> None:
        prefix = '\r\033[2K' if interactive else ''
        ending = '\n' if not interactive or (final and (finish_line or state == 'cancelled')) else ''
        text = (render(label, status, remaining, seconds, pretty, state)
                if interactive and pretty is not None and pretty.enabled
                else f'{label} · {status}')
        bell = '\a' if final and state == 'complete' and interactive else ''
        print(f'{prefix}{text}{bell}', end=ending, flush=True)

    try:
        display(f'{format_duration(seconds)} remaining', seconds)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if interactive:
                display(f'{format_duration(math.ceil(remaining))} remaining', remaining)
            time.sleep(min(1, remaining))
    except KeyboardInterrupt:
        remaining = max(0, math.ceil(deadline - time.monotonic()))
        display(f'cancelled at {format_duration(remaining)} remaining', remaining,
                state='cancelled', final=True)
        raise
    display(completion, 0, state='complete', final=True)
