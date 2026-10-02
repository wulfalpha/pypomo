"""Optional JSON configuration."""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from .durations import DEFAULT_UNITS, parse_duration


@dataclass
class Config:
    default_units: str | None = None
    timers: dict[str, int] = field(default_factory=lambda: {'pomo': 1500})


def default_config_path() -> Path:
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'pypomo' / 'config.json'


def load_config(path: Path, *, required: bool = False) -> Config:
    config = Config()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        if not required:
            return config
        raise ValueError(f'Config file not found: {path}') from None
    except (OSError, ValueError) as exc:
        raise ValueError(f'Cannot read config {path}: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError('Config must be a JSON object.')
    unknown = data.keys() - {'default_units', 'timers'}
    if unknown:
        raise ValueError(f"Unknown config settings: {', '.join(sorted(unknown))}")
    if 'default_units' in data:
        unit = data['default_units']
        if not isinstance(unit, str) or unit not in DEFAULT_UNITS:
            raise ValueError('default_units must be seconds, minutes, hours, s, m, or h.')
        config.default_units = unit
    timers = data.get('timers', {})
    if not isinstance(timers, dict):
        raise ValueError('timers must map names to duration strings.')
    for name, duration in timers.items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', name):
            raise ValueError(f'Invalid timer name {name!r}: start with a letter; use letters, digits, _ or -.')
        if not isinstance(duration, str):
            raise ValueError(f'Timer {name!r} must contain a duration string.')
        try:
            config.timers[name] = parse_duration(duration, config.default_units)
        except ValueError as exc:
            raise ValueError(f'Timer {name!r}: {exc}') from exc
    return config
