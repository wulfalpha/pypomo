"""Countdown execution using a monotonic clock."""
import math
import sys
import time


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


def run_timer(seconds: int, label: str) -> None:
    interactive = sys.stdout.isatty()
    print(f'{label}: {format_duration(seconds)}', flush=True)
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if interactive:
            print(f'\r{format_duration(math.ceil(remaining))}', end='', flush=True)
        time.sleep(min(1, remaining))
    if interactive:
        print('\r00:00:00\a', flush=True)
    print(f'{label}: done!')
