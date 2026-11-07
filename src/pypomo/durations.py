"""Duration parsing shared by CLI and configuration."""
import re

UNITS = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
MAX_SECONDS = 365 * 86400
DURATION_RE = re.compile(r'(?:[0-9]+[dhms])+')
SPACED_RE = re.compile(r'(?:[0-9]+[dhms])+(?: +(?:[0-9]+[dhms])+)+')
DEFAULT_UNITS = {'s': 's', 'seconds': 's', 'm': 'm', 'minutes': 'm', 'h': 'h', 'hours': 'h',
                 'd': 'd', 'days': 'd'}
UNITS_MESSAGE = 'default_units must be seconds, minutes, hours, days, s, m, h, or d.'
SPACED_MESSAGE = 'Spaces are allowed only between units, as in 1h 30m.'


def parse_duration(value: str, default_units: str | None = None) -> int:
    if any(char.isspace() for char in value):
        if not SPACED_RE.fullmatch(value):
            raise ValueError(SPACED_MESSAGE)
        value = value.replace(' ', '')
    if re.fullmatch(r'[0-9]+', value):
        if default_units is None:
            raise ValueError('Missing units: use 15s, 15m, 15h, or 15d, or configure default_units.')
        if default_units not in DEFAULT_UNITS:
            raise ValueError(UNITS_MESSAGE)
        value += DEFAULT_UNITS[default_units]
    if not DURATION_RE.fullmatch(value):
        raise ValueError('Invalid duration: use whole numbers with d, h, m, or s (e.g. 1h30m15s).')
    total, previous = 0, UNITS['d'] + 1
    for amount, unit in re.findall(r'([0-9]+)([dhms])', value):
        multiplier = UNITS[unit]
        if multiplier >= previous:
            raise ValueError('Duration units must appear once each, in order: d, h, m, s.')
        amount = amount.lstrip('0') or '0'
        if len(amount) > len(str(MAX_SECONDS)):
            raise ValueError('Duration too long: maximum is 365 days (365d).')
        total += int(amount) * multiplier
        if total > MAX_SECONDS:
            raise ValueError('Duration too long: maximum is 365 days (365d).')
        previous = multiplier
    if total <= 0:
        raise ValueError('Duration must be greater than zero.')
    return total
