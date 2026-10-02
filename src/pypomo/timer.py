"""Countdown execution using a monotonic clock."""
import math
import sys
import time


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


def run_timer(seconds: int, label: str, *, live: bool = False) -> None:
    interactive = live or sys.stdout.isatty()
    deadline = time.monotonic() + seconds

    def display(status: str, *, final: bool = False) -> None:
        prefix = '\r\033[2K' if interactive else ''
        ending = '\n' if final or not interactive else ''
        print(f'{prefix}{label} · {status}', end=ending, flush=True)

    try:
        display(f'{format_duration(seconds)} remaining')
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if interactive:
                display(f'{format_duration(math.ceil(remaining))} remaining')
            time.sleep(min(1, remaining))
    except KeyboardInterrupt:
        remaining = max(0, math.ceil(deadline - time.monotonic()))
        display(f'cancelled at {format_duration(remaining)} remaining', final=True)
        raise
    display('complete' + ('\a' if interactive else ''), final=True)
