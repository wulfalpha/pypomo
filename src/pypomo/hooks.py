"""Run user commands on timer events, without waiting for them."""
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

EVENTS = ('start', 'end', 'pause', 'resume', 'cancel')
HOOK_KEYS = (*EVENTS, 'any')

Command = str | list[str]
# Receives an event name and the whole seconds remaining in the current timer.
EventHandler = Callable[[str, int], None]


def parse_hooks(data: object) -> dict[str, list[Command]]:
    """Validate a [hooks] table: event name -> shell string or argv list."""
    if not isinstance(data, dict):
        raise ValueError('hooks must be an object/table.')
    unknown = data.keys() - set(HOOK_KEYS)
    if unknown:
        raise ValueError(f"Unknown hooks: {', '.join(sorted(unknown))}. "
                         f"Use {', '.join(HOOK_KEYS)}.")
    result: dict[str, list[Command]] = {}
    for event, command in data.items():
        if isinstance(command, str) and command.strip():
            result[event] = [command]
        elif (isinstance(command, list) and command
              and all(isinstance(part, str) for part in command) and command[0]):
            result[event] = [list(command)]
        else:
            raise ValueError(f'hooks.{event} must be a command string or a nonempty list of '
                             f'strings; got {command!r}.')
    return result


@dataclass(frozen=True)
class Phase:
    """What a hook is told about the timer that produced an event."""
    label: str
    phase: str
    duration: int
    round: int | None = None
    rounds: int | None = None
    last: bool = True


class HookRunner:
    """Starts configured commands in the background and never lets them stop the timer.

    String commands run through the system shell; lists run directly. Commands
    get PYPOMO_* environment variables, no stdin, and discarded stdout; stderr is
    inherited so their errors stay visible. Each runs in its own session, so
    Ctrl+C or a closing terminal does not interrupt a hook already running.
    """

    def __init__(self, commands: Mapping[str, list[Command]], timer: str):
        self.commands = {event: list(items) for event, items in commands.items() if items}
        self.timer = timer
        self.running: list[subprocess.Popen[bytes]] = []
        self.failed: set[str] = set()

    def __bool__(self) -> bool:
        return bool(self.commands)

    def handler(self, phase: Phase) -> EventHandler:
        return lambda event, remaining: self.emit(event, phase, remaining)

    def emit(self, event: str, phase: Phase, remaining: int) -> None:
        commands = self.commands.get(event, []) + self.commands.get('any', [])
        if not commands:
            return
        env = dict(os.environ,
                   PYPOMO_EVENT=event,
                   PYPOMO_TIMER=self.timer,
                   PYPOMO_LABEL=phase.label,
                   PYPOMO_PHASE=phase.phase,
                   PYPOMO_ROUND='' if phase.round is None else str(phase.round),
                   PYPOMO_ROUNDS='' if phase.rounds is None else str(phase.rounds),
                   PYPOMO_DURATION=str(phase.duration),
                   PYPOMO_REMAINING=str(remaining),
                   PYPOMO_LAST='1' if phase.last else '0')
        self.running = [process for process in self.running if process.poll() is None]
        for command in commands:
            self._start(command, env)

    def _start(self, command: Command, env: dict[str, str]) -> None:
        options: dict[str, object] = {}
        if sys.platform == 'win32':
            options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options['start_new_session'] = True
        try:
            self.running.append(subprocess.Popen(
                command, shell=isinstance(command, str), env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, **options))
        except (OSError, ValueError) as exc:
            name = command if isinstance(command, str) else ' '.join(command)
            if name not in self.failed:  # Warn once per command, not on every event.
                self.failed.add(name)
                try:
                    print(f'\npypomo: hook could not start: {name}: {exc}', file=sys.stderr, flush=True)
                except (OSError, ValueError, AttributeError):
                    pass
