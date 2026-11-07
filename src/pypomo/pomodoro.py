"""Finite Pomodoro routines and their configuration."""
from collections.abc import Iterator
from dataclasses import dataclass, replace

from .durations import parse_duration
from .keys import Keyboard
from .pretty import Pretty, section
from .timer import run_timer, wait_for_start

MAX_ROUNDS = 1000


@dataclass
class Pomodoro:
    focus: int = 1500
    short_break: int = 300
    long_break: int = 900
    rounds: int = 4
    auto_start: bool = True

    def phases(self) -> Iterator[tuple[str, int, int]]:
        for round_number in range(1, self.rounds + 1):
            yield 'focus', self.focus, round_number
            if round_number < self.rounds:
                yield 'short break', self.short_break, round_number
            else:
                yield 'long break', self.long_break, round_number


def parse_pomodoro(data: object, base: Pomodoro, units: str | None, name: str) -> Pomodoro:
    values = section(data, {'focus', 'short_break', 'long_break', 'rounds', 'auto_start'}, name)
    result = replace(base)
    for key, value in values.items():
        if key == 'rounds':
            if type(value) is not int or not 1 <= value <= MAX_ROUNDS:
                raise ValueError(f'{name}.rounds must be an integer from 1 to {MAX_ROUNDS}.')
        elif key == 'auto_start':
            if type(value) is not bool:
                raise ValueError(f'{name}.auto_start must be a boolean; got {value!r}.')
        else:
            if not isinstance(value, str):
                raise ValueError(f'{name}.{key} must be a duration string.')
            try:
                value = parse_duration(value, units)
            except ValueError as exc:
                raise ValueError(f'{name}.{key}: {exc}') from exc
        setattr(result, key, value)
    return result


def run_pomodoro(routine: Pomodoro, label: str, *, live: bool = False,
                 pretty: Pretty | None = None, silent: bool = False,
                 keys: Keyboard | None = None) -> None:
    for index, (phase, seconds, round_number) in enumerate(routine.phases()):
        final = phase == 'long break'
        phase_label = f'{label} · {phase} {round_number}/{routine.rounds}'
        if index and not routine.auto_start:
            wait_for_start(seconds, phase_label, live=live, pretty=pretty, keys=keys)
        run_timer(seconds, phase_label, live=live, pretty=pretty, silent=silent, finish_line=final,
                  completion='routine complete' if final else 'complete', keys=keys)
