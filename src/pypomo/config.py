"""Optional TOML or JSON configuration."""
import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .durations import DEFAULT_UNITS, parse_duration
from .pomodoro import Pomodoro, parse_pomodoro
from .pretty import Pretty, parse_pretty

NAME_RE = re.compile(r'[A-Za-z][A-Za-z0-9_-]*')


@dataclass
class Config:
    default_units: str | None = None
    timers: dict[str, int] = field(default_factory=dict)
    pretty: Pretty = field(default_factory=Pretty)
    pomo: Pomodoro = field(default_factory=Pomodoro)
    pomodoros: dict[str, Pomodoro] = field(default_factory=dict)


def default_config_path() -> Path:
    xdg = os.environ.get('XDG_CONFIG_HOME')
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / '.config'
    directory = base / 'pypomo'
    toml = directory / 'config.toml'
    legacy = directory / 'config.json'
    return toml if toml.exists() or not legacy.exists() else legacy


def load_config(path: Path, *, required: bool = False) -> Config:
    config = Config()
    try:
        content = path.read_text(encoding='utf-8-sig')
        if path.suffix.lower() == '.toml':
            data = tomllib.loads(content)
        elif path.suffix.lower() == '.json':
            data = json.loads(content)
        else:
            raise ValueError('Config file must use .toml or .json.')
    except FileNotFoundError:
        if not required:
            return config
        raise ValueError(f'Config file not found: {path}') from None
    except (OSError, ValueError) as exc:
        raise ValueError(f'Cannot read config {path}: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError('Config must be an object/table.')
    unknown = data.keys() - {'default_units', 'timers', 'pretty', 'pomo', 'pomodoros'}
    if unknown:
        raise ValueError(f"Unknown config settings: {', '.join(sorted(unknown))}")
    if 'default_units' in data:
        unit = data['default_units']
        if not isinstance(unit, str) or unit not in DEFAULT_UNITS:
            raise ValueError('default_units must be seconds, minutes, hours, s, m, or h.')
        config.default_units = unit
    config.pretty = parse_pretty(data.get('pretty', {}))
    timers = data.get('timers', {})
    if not isinstance(timers, dict):
        raise ValueError('timers must map names to duration strings.')
    for name, duration in timers.items():
        if not NAME_RE.fullmatch(name):
            raise ValueError(f'Invalid timer name {name!r}: start with a letter; use letters, digits, _ or -.')
        if not isinstance(duration, str):
            raise ValueError(f'Timer {name!r} must contain a duration string.')
        try:
            config.timers[name] = parse_duration(duration, config.default_units)
        except ValueError as exc:
            raise ValueError(f'Timer {name!r}: {exc}') from exc
    legacy_focus = config.timers.pop('pomo', config.pomo.focus)
    config.pomo = parse_pomodoro(data.get('pomo', {}), Pomodoro(focus=legacy_focus),
                                 config.default_units, 'pomo')
    routines = data.get('pomodoros', {})
    if not isinstance(routines, dict):
        raise ValueError('pomodoros must map names to routine settings.')
    for name, settings in routines.items():
        if not NAME_RE.fullmatch(name):
            raise ValueError(f'Invalid Pomodoro name {name!r}: start with a letter; use letters, digits, _ or -.')
        config.pomodoros[name] = parse_pomodoro(settings, config.pomo, config.default_units,
                                               f'pomodoros.{name}')
    return config
