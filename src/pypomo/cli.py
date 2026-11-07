"""argparse entry point."""
import argparse
import sys
import textwrap
from dataclasses import replace
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .config import NAME_RE, Config, default_config_path, load_config
from .durations import DURATION_RE, parse_duration
from .events import Events, JsonLines, Phase
from .hooks import HookRunner
from .keys import keyboard
from .output import flush, silence_broken_pipe, write
from .pomodoro import Pomodoro, run_pomodoro
from .signals import Terminated, cancellation_handlers
from .timer import format_duration, run_timer


class ArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        if file is sys.stdout:
            if message:
                write(message, end='')
        else:
            super()._print_message(message, file)


DURATIONS_HELP = 'Durations combine d, h, m, and s in that order: 25m, 1h30m, 1h 30m, or 2d.'
KEYS_HELP = ('While a timer runs in a terminal, press p or Space to pause and resume, '
             'or q to cancel.')


def end_time(seconds: int, now: datetime | None = None) -> str:
    """Local clock time `seconds` from now, to the nearest minute; dated when not today."""
    now = now or datetime.now()
    end = now + timedelta(seconds=seconds)
    end = (end + timedelta(seconds=30)).replace(second=0, microsecond=0)
    return end.strftime('%H:%M' if end.date() == now.date() else '%Y-%m-%d %H:%M')


def main(argv: list[str] | None = None) -> int:
    try:
        with cancellation_handlers():
            try:
                return _main(argv)
            finally:
                # Keep buffered output failures inside the broken-pipe boundary.
                flush()
    except BrokenPipeError:
        silence_broken_pipe()
        return 141
    except Terminated as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130


def _main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parse_args(parser, argv)
    try:
        config = load_config(args.config or default_config_path(), required=args.config is not None)
        if args.list:
            list_timers(config)
            return 0
        target = resolve(args.timer, config)
    except ValueError as exc:
        parser.error(str(exc))
    if isinstance(target, Pomodoro) and args.auto_start is not None:
        target = replace(target, auto_start=args.auto_start)
    if args.preview:
        preview(args.timer, target)
        return 0
    pretty = replace(config.pretty, enabled=args.pretty) if args.pretty is not None else config.pretty
    hooks = hook_runner(args, config)
    jsonl = args.format == 'jsonl'
    events = Events([listener for listener in (hooks, JsonLines(args.timer) if jsonl else None) if listener])
    events = events or None
    with keyboard() as keys:
        if isinstance(target, Pomodoro):
            run_pomodoro(target, args.timer, live=args.live, pretty=pretty, silent=args.silent, keys=keys,
                         events=events, display=not jsonl)
        else:
            on_event = events.handler(Phase(args.timer, 'timer', target)) if events else None
            run_timer(target, args.timer, live=args.live, pretty=pretty, silent=args.silent, keys=keys,
                      on_event=on_event, display=not jsonl)
    return 0


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description='Start a duration or named timer (e.g. 15m, 1h30m, pomo).',
        epilog='\n\n'.join(textwrap.fill(text, 79) for text in (DURATIONS_HELP, KEYS_HELP)),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('timer', nargs='?', help='duration, timer name, pomo, or NAME.pomo')
    parser.add_argument('--config', type=Path, help='TOML or JSON config path (default: XDG config directory or ~/.config/pypomo)')
    parser.add_argument('--list', action='store_true', help='list available timers and Pomodoro routines')
    parser.add_argument('--live', action='store_true', help='update one line even when output is piped')
    parser.add_argument('--silent', action='store_true', help='suppress the completion bell')
    parser.add_argument('--preview', action='store_true', help='show phases and total duration without starting a timer')
    parser.add_argument('--pretty', action=argparse.BooleanOptionalAction, default=None,
                        help='enable styled output (or --no-pretty to disable it)')
    parser.add_argument('--hook', action='append', default=[], metavar='CMD',
                        help='run CMD through the shell on every timer event (repeatable)')
    parser.add_argument('--no-hooks', action='store_true', help='ignore hooks from the config file')
    parser.add_argument('--format', choices=('text', 'jsonl'), default='text',
                        help='text: the countdown display (default); jsonl: one JSON object per '
                             'event on stdout, with no display')
    parser.add_argument('--auto-start', action=argparse.BooleanOptionalAction, default=None,
                        help='start each Pomodoro phase automatically (or --no-auto-start '
                             'to wait for Enter between phases)')
    try:
        package_version = version('pypomo')
    except PackageNotFoundError:
        package_version = 'unknown (source checkout)'
    parser.add_argument('--version', action='version', version=f'pypomo {package_version}')
    return parser


def parse_args(parser: ArgumentParser, argv: list[str] | None) -> argparse.Namespace:
    """Parse and cross-check arguments, joining an unquoted spaced duration such as 1h 30m."""
    args, extras = parser.parse_known_args(argv)
    if extras:
        if any(value.startswith('-') and value[1:2].isdigit() for value in extras):
            parser.error('Duration must be greater than zero.')
        if not (args.timer and DURATION_RE.fullmatch(args.timer)
                and all(DURATION_RE.fullmatch(value) for value in extras)):
            parser.error(f"unrecognized arguments: {' '.join(extras)}")
        args.timer = ' '.join([args.timer, *extras])
    if args.timer is None and not args.list:
        parser.error('provide a duration or timer name, or use --list')
    if args.timer is not None and args.list:
        parser.error('use --list without a timer')
    if args.preview and args.list:
        parser.error('use --preview with a timer or routine, not --list')
    if args.format == 'jsonl':
        for flag, used in (('--list', args.list), ('--preview', args.preview), ('--live', args.live)):
            if used:
                parser.error(f'--format jsonl is for running timers; it cannot be used with {flag}')
    return args


def resolve(name: str, config: Config) -> Pomodoro | int:
    """Return the routine or the number of seconds that `name` refers to."""
    if name == 'pomo':
        return config.pomo
    if name.endswith('.pomo'):
        routine = config.pomodoros.get(name[:-5])
        if routine is None:
            raise ValueError(f'Unknown Pomodoro routine {name!r}. Use --list to see available routines.')
        return routine
    if name in config.timers:
        return config.timers[name]
    if NAME_RE.fullmatch(name):
        raise ValueError(f'Unknown timer {name!r}. Use --list to see available timers.')
    return parse_duration(name, config.default_units)


def list_timers(config: Config) -> None:
    for name, seconds in sorted(config.timers.items()):
        write(f'{name}: {format_duration(seconds)}')
    routines = {'pomo': config.pomo, **{f'{name}.pomo': value for name, value in config.pomodoros.items()}}
    for name, routine in sorted(routines.items()):
        write(f'{name}: {routine.rounds} focus rounds · focus {format_duration(routine.focus)}'
              f' · short break {format_duration(routine.short_break)}'
              f' · long break {format_duration(routine.long_break)}'
              + ('' if routine.auto_start else ' · waits between phases'))


def preview(name: str, target: Pomodoro | int) -> None:
    if isinstance(target, Pomodoro):
        total = 0
        for phase, duration, round_number in target.phases():
            write(f'{name} · {phase} {round_number}/{target.rounds}: {format_duration(duration)}')
            total += duration
    else:
        total = target
        write(f'{name}: {format_duration(target)}')
    write(f'Total: {format_duration(total)}')
    waits = isinstance(target, Pomodoro) and not target.auto_start
    write(f"Ends: {end_time(total)} if started now{', plus time waiting between phases' if waits else ''}")


def hook_runner(args: argparse.Namespace, config: Config) -> HookRunner | None:
    """Configured hooks (unless --no-hooks) plus --hook commands, which run on every event."""
    commands = {} if args.no_hooks else dict(config.hooks)
    if args.hook:
        commands['any'] = commands.get('any', []) + args.hook
    return HookRunner(commands, args.timer) if commands else None
