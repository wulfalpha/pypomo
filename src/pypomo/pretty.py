"""Validated display settings and terminal styling."""
from dataclasses import dataclass, field, fields
import unicodedata

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
            elif key == 'width':
                valid = type(value) is int and 1 <= value <= 80
            elif key in ('filled', 'empty'):
                valid = (isinstance(value, str) and len(value) == 1
                         and (value == ' ' or unicodedata.category(value)[0] in 'LNPS')
                         and unicodedata.east_asian_width(value) not in ('W', 'F'))
            else:
                valid = isinstance(value, str) and value in COLORS
            if not valid:
                raise ValueError(f'Invalid {name}.{key}: {value!r}. Use booleans for enabled, '
                                 'width 1–80, single narrow printable bar characters, '
                                 'and named colors (black, red, green, yellow, blue, magenta, cyan, white, default).')
            setattr(target, key, value)
    return result


def render(label: str, status: str, remaining: float, total: int,
           settings: Pretty, state: str = 'remaining') -> str:
    def color(text: str, role: str) -> str:
        if not settings.colors.enabled:
            return text
        return f'\033[{COLORS[getattr(settings.colors, role)]}m{text}\033[0m'

    parts = [color(label, 'label')]
    if settings.bar.enabled:
        width = settings.bar.width
        filled = min(width, max(0, int(width * (1 - remaining / total))))
        bar = settings.bar.filled * filled + settings.bar.empty * (width - filled)
        parts.append(color(f'[{bar}]', 'bar'))
    parts.append(color(status, state))
    return ' · '.join(parts)
