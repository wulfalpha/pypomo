"""argparse entry point."""
import argparse
import sys
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .config import NAME_RE, default_config_path, load_config
from .durations import DURATION_RE, SPACED_MESSAGE, parse_duration
from .output import flush, silence_broken_pipe, write
from .pomodoro import run_pomodoro
from .signals import Terminated, cancellation_handlers
from .timer import format_duration, run_timer


class ArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        if file is sys.stdout:
            if message:
                write(message, end='')
        else:
            super()._print_message(message, file)


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
    parser = ArgumentParser(
        description='Start a duration or named timer (e.g. 15m, 1h30m, pomo).',
        epilog=SPACED_MESSAGE,
    )
    parser.add_argument('timer', nargs='?', help='duration, timer name, pomo, or NAME.pomo')
    parser.add_argument('--config', type=Path, help='TOML or JSON config path (default: XDG config directory or ~/.config/pypomo)')
    parser.add_argument('--list', action='store_true', help='list available timers and Pomodoro routines')
    parser.add_argument('--live', action='store_true', help='update one line even when output is piped')
    parser.add_argument('--silent', action='store_true', help='suppress the completion bell')
    parser.add_argument('--preview', action='store_true', help='show phases and total duration without starting a timer')
    parser.add_argument('--pretty', action=argparse.BooleanOptionalAction, default=None,
                        help='enable styled output (or --no-pretty to disable it)')
    try:
        package_version = version('pypomo')
    except PackageNotFoundError:
        package_version = 'unknown (source checkout)'
    parser.add_argument('--version', action='version', version=f'pypomo {package_version}')
    args, extras = parser.parse_known_args(argv)
    if extras:
        if any(value.startswith('-') and value[1:2].isdigit() for value in extras):
            parser.error('Duration must be greater than zero.')
        if args.timer and DURATION_RE.fullmatch(args.timer) and all(
            DURATION_RE.fullmatch(value) for value in extras
        ):
            parser.error(SPACED_MESSAGE)
        parser.error(f"unrecognized arguments: {' '.join(extras)}")
    if args.timer is None and not args.list:
        parser.error('provide a duration or timer name, or use --list')
    if args.timer is not None and args.list:
        parser.error('use --list without a timer')
    if args.preview and args.list:
        parser.error('use --preview with a timer or routine, not --list')
    try:
        config = load_config(args.config or default_config_path(), required=args.config is not None)
        if args.list:
            for name, seconds in sorted(config.timers.items()):
                write(f'{name}: {format_duration(seconds)}')
            routines = {'pomo': config.pomo, **{f'{name}.pomo': value for name, value in config.pomodoros.items()}}
            for name, routine in sorted(routines.items()):
                write(f'{name}: {routine.rounds} focus rounds · focus {format_duration(routine.focus)}'
                      f' · short break {format_duration(routine.short_break)}'
                      f' · long break {format_duration(routine.long_break)}')
            return 0
        routine = None
        if args.timer == 'pomo':
            routine = config.pomo
        elif args.timer.endswith('.pomo'):
            routine = config.pomodoros.get(args.timer[:-5])
            if routine is None:
                raise ValueError(f'Unknown Pomodoro routine {args.timer!r}. Use --list to see available routines.')
        elif args.timer in config.timers:
            seconds = config.timers[args.timer]
        elif NAME_RE.fullmatch(args.timer):
            raise ValueError(f'Unknown timer {args.timer!r}. Use --list to see available timers.')
        else:
            seconds = parse_duration(args.timer, config.default_units)
    except ValueError as exc:
        parser.error(str(exc))
    if args.preview:
        if routine is not None:
            total = 0
            for phase, duration, round_number in routine.phases():
                write(f'{args.timer} · {phase} {round_number}/{routine.rounds}: {format_duration(duration)}')
                total += duration
        else:
            total = seconds
            write(f'{args.timer}: {format_duration(seconds)}')
        write(f'Total: {format_duration(total)}')
        return 0
    pretty = replace(config.pretty, enabled=args.pretty) if args.pretty is not None else config.pretty
    if routine is not None:
        run_pomodoro(routine, args.timer, live=args.live, pretty=pretty, silent=args.silent)
    else:
        run_timer(seconds, args.timer, live=args.live, pretty=pretty, silent=args.silent)
    return 0
