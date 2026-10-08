"""Validated display settings and terminal styling."""
import os
import unicodedata
from dataclasses import dataclass, field, fields

from .output import safe_text

COLORS = dict(zip(
    ('black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'),
    range(30, 38),
))
COLORS['default'] = 39


@dataclass
class Bar:
    enabled: bool = True
    width: int = 20
    filled: str = '█'
    empty: str = '░'


@dataclass
class Colors:
    enabled: bool = True
    label: str = 'cyan'
    remaining: str = 'white'
    bar: str = 'green'
    complete: str = 'green'
    cancelled: str = 'yellow'


@dataclass
class Pretty:
    enabled: bool = False
    bar: Bar = field(default_factory=Bar)
    colors: Colors = field(default_factory=Colors)


def section(data: object, allowed: set[str], name: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f'{name} must be an object/table.')
    unknown = data.keys() - allowed
    if unknown:
        raise ValueError(f"Unknown {name} settings: {', '.join(sorted(unknown))}")
    return data


def parse_pretty(data: object) -> Pretty:
    data = section(data, {'enabled', 'bar', 'colors'}, 'pretty')
    result = Pretty()
    for name, target in (('pretty', result), ('bar', result.bar), ('colors', result.colors)):
        values = data if name == 'pretty' else section(
            data.get(name, {}), {item.name for item in fields(target)}, f'pretty.{name}'
        )
        for key, value in values.items():
            if name == 'pretty' and key in ('bar', 'colors'):
                continue
            if key == 'enabled':
                valid = type(value) is bool
                expected = 'a boolean'
            elif key == 'width':
                valid = type(value) is int and 1 <= value <= 80
                expected = 'an integer from 1 to 80'
            elif key in ('filled', 'empty'):
                valid = (isinstance(value, str) and len(value) == 1
                         and (value == ' ' or unicodedata.category(value)[0] in 'LNPS')
                         and unicodedata.east_asian_width(value) not in ('W', 'F'))
                expected = 'a single narrow printable character'
            else:
                valid = isinstance(value, str) and value in COLORS
                expected = f"one of {', '.join(COLORS)}"
            if not valid:
                path = name if name == 'pretty' else f'pretty.{name}'
                raise ValueError(f'{path}.{key} must be {expected}; got {value!r}.')
            setattr(target, key, value)
    return result


def render(label: str, status: str, remaining: float, total: int,
           settings: Pretty, state: str = 'remaining', *, columns: int | None = None) -> str:
    def color(text: str, role: str) -> str:
        if not settings.colors.enabled or os.environ.get('NO_COLOR') or os.environ.get('TERM') == 'dumb':
            return text
        return f'\033[{COLORS[getattr(settings.colors, role)]}m{text}\033[0m'

    separator = safe_text(' · ', ' - ')
    label, status = safe_text(label), safe_text(status)
    width = settings.bar.width if settings.bar.enabled else 0
    if columns is not None:
        # Leave the last column unused to avoid terminal auto-wrap. Preserve status
        # before the label, and omit the bar when the text needs the space.
        budget = max(0, columns - 1)
        width = min(width, max(0, budget - len(label) - len(status) - 2 * len(separator) - 2))
        if len(label) + len(separator) + len(status) > budget:
            available = budget - len(separator) - len(status)
            label = (label[:max(0, available - 1)] + '~') if available > 0 else ''
            if not label:
                return color(status[:budget], state)
    parts = [color(label, 'label')]
    if width:
        filled = min(width, max(0, int(width * (1 - remaining / total))))
        bar = safe_text(settings.bar.filled, '#') * filled + safe_text(settings.bar.empty, '-') * (width - filled)
        parts.append(color(f'[{bar}]', 'bar'))
    parts.append(color(status, state))
    return separator.join(parts)
