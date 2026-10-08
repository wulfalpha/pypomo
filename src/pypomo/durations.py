"""Duration parsing shared by CLI and configuration."""
import re

UNITS = {'s': 1, 'm': 60, 'h': 3600}
MAX_SECONDS = 365 * 86400
DURATION_RE = re.compile(r'(?:[0-9]+[hms])+')
DEFAULT_UNITS = {'s': 's', 'seconds': 's', 'm': 'm', 'minutes': 'm', 'h': 'h', 'hours': 'h'}
SPACED_MESSAGE = ('Pre-1.0 versions do not yet support compound durations with spaces. '
                  'Use 1h30m instead of 1h 30m.')


def parse_duration(value: str, default_units: str | None = None) -> int:
    if any(char.isspace() for char in value):
        raise ValueError(SPACED_MESSAGE)
    if re.fullmatch(r'[0-9]+', value):
        if default_units is None:
            raise ValueError('Missing units: use 15s, 15m, or 15h, or configure default_units.')
        if default_units not in DEFAULT_UNITS:
            raise ValueError('default_units must be seconds, minutes, hours, s, m, or h.')
        value += DEFAULT_UNITS[default_units]
    if not DURATION_RE.fullmatch(value):
        raise ValueError('Invalid duration: use whole numbers with s, m, or h (e.g. 1h30m15s).')
    total, previous = 0, 3601
    for amount, unit in re.findall(r'([0-9]+)([hms])', value):
        multiplier = UNITS[unit]
        if multiplier >= previous:
            raise ValueError('Duration units must appear once each, in order: h, m, s.')
        amount = amount.lstrip('0') or '0'
        if len(amount) > len(str(MAX_SECONDS)):
            raise ValueError('Duration too long: maximum is 365 days (8760h).')
        total += int(amount) * multiplier
        if total > MAX_SECONDS:
            raise ValueError('Duration too long: maximum is 365 days (8760h).')
        previous = multiplier
    if total <= 0:
        raise ValueError('Duration must be greater than zero.')
    return total
