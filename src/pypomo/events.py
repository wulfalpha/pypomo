"""Timer events and the listeners that receive them (hooks and JSON lines)."""
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from .output import write

EVENTS = ('start', 'end', 'pause', 'resume', 'cancel', 'wait')

# Called by a running timer with an event name and the whole seconds remaining.
EventHandler = Callable[[str, int], None]


@dataclass(frozen=True)
class Phase:
    """What listeners are told about the timer or routine phase behind an event."""
    label: str
    phase: str
    duration: int
    round: int | None = None
    rounds: int | None = None
    last: bool = True


# Receives the event name, its phase, and the whole seconds remaining.
Listener = Callable[[str, Phase, int], None]


class Events:
    """Fans each timer event out to every listener."""

    def __init__(self, listeners: Sequence[Listener]):
        self.listeners = list(listeners)

    def __bool__(self) -> bool:
        return bool(self.listeners)

    def handler(self, phase: Phase) -> EventHandler:
        def emit(event: str, remaining: int) -> None:
            for listener in self.listeners:
                listener(event, phase, remaining)
        return emit


def event_record(event: str, timer: str, phase: Phase, remaining: int,
                 now: datetime | None = None) -> dict[str, object]:
    return {
        'event': event,
        'timer': timer,
        'label': phase.label,
        'phase': phase.phase,
        'round': phase.round,
        'rounds': phase.rounds,
        'duration': phase.duration,
        'remaining': remaining,
        'last': phase.last,
        'time': (now or datetime.now().astimezone()).isoformat(timespec='seconds'),
    }


class JsonLines:
    """Writes one ASCII JSON object per event to stdout, flushed immediately."""

    def __init__(self, timer: str):
        self.timer = timer

    def __call__(self, event: str, phase: Phase, remaining: int) -> None:
        write(json.dumps(event_record(event, self.timer, phase, remaining)))
