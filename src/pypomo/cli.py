"""argparse entry point."""
import argparse
import re
from pathlib import Path
from .config import default_config_path, load_config
from .durations import SPACED_MESSAGE, parse_duration
from .timer import format_duration, run_timer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Start a duration or named timer (e.g. 15m, 1h30m, pomo).',
        epilog=SPACED_MESSAGE,
    )
    parser.add_argument('timer', nargs='?', help='duration or configured timer name')
    parser.add_argument('--config', type=Path, help=f'JSON config path (default: {default_config_path()})')
    parser.add_argument('--list', action='store_true', help='list available named timers')
    parser.add_argument('--live', action='store_true', help='update one line even when output is piped')
    parser.add_argument('--version', action='version', version='pypomo 0.1.0')
    args, extras = parser.parse_known_args(argv)
    if extras:
        if args.timer and re.fullmatch(r'(?:[0-9]+[hms])+', args.timer) and all(
            re.fullmatch(r'(?:[0-9]+[hms])+', value) for value in extras
        ):
            parser.error(SPACED_MESSAGE)
        parser.error(f"unrecognized arguments: {' '.join(extras)}")
    if args.timer is None and not args.list:
        parser.error('provide a duration or timer name, or use --list')
    if args.timer is not None and args.list:
        parser.error('use --list without a timer')
    try:
        config = load_config(args.config or default_config_path(), required=args.config is not None)
        if args.list:
            for name, seconds in sorted(config.timers.items()):
                print(f'{name}: {format_duration(seconds)}')
            return 0
        if args.timer in config.timers:
            seconds = config.timers[args.timer]
        else:
            seconds = parse_duration(args.timer, config.default_units)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        run_timer(seconds, args.timer, live=args.live)
    except KeyboardInterrupt:
        return 130
    return 0
