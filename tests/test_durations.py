"""Duration parsing: syntax, units, spacing, and limits."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import disable_keyboard, run_cli

from pypomo.cli import main
from pypomo.config import Config, load_config
from pypomo.durations import MAX_SECONDS, parse_duration
from pypomo.pomodoro import MAX_ROUNDS, Pomodoro, parse_pomodoro

setUpModule = disable_keyboard


class DurationTests(unittest.TestCase):
    def test_supported_durations(self):
        for value, expected in [('30s', 30), ('15m', 900), ('2h', 7200),
                                ('1h30m15s', 5415), ('90m', 5400), ('1h0m', 3600)]:
            with self.subTest(value=value):
                self.assertEqual(parse_duration(value), expected)
        for units in ('m', 'minutes'):
            self.assertEqual(parse_duration('15', units), 900)
            self.assertEqual(parse_duration('15s', units), 15)

    def test_invalid_durations(self):
        for value in ('', '0s', '-1m', '1.5h', '1m1h', '1h1h', '15', '1x', '1h30'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value)

    def test_days(self):
        for value, expected in [('1d', 86400), ('2d12h', 216000), ('1d 2h 3m 4s', 93784),
                                ('365d', 365 * 86400), ('0d5m', 300)]:
            with self.subTest(value=value):
                self.assertEqual(parse_duration(value), expected)
        for units in ('d', 'days'):
            self.assertEqual(parse_duration('2', units), 172800)
        for value, message in (('366d', 'maximum is 365 days'), ('364d24h1s', 'maximum is 365 days'),
                               ('1h1d', 'in order: d, h, m, s'), ('1d1d', 'in order'), ('1D', 'Invalid')):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, message):
                parse_duration(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('default_units = "days"\n[timers]\nweek = "7"\nsprint = "1d 12h"\n')
            self.assertEqual(load_config(path).timers, {'week': 604800, 'sprint': 129600})
        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.cli.run_timer') as timer:
            self.assertEqual(main(['2d', '6h']), 0)
            self.assertEqual(timer.call_args.args, (194400, '2d 6h'))

    def test_spaced_duration(self):
        for value, expected in [('1h 30m', 5400), ('1h  30m 15s', 5415), ('1h30m 15s', 5415),
                                ('2h 0m', 7200)]:
            with self.subTest(value=value):
                self.assertEqual(parse_duration(value), expected)
        self.assertEqual(parse_duration('1h 30m', 'm'), 5400)
        for value in ('5 m', ' 1h 30m', '1h 30m ', '1h\t30m', '1h\n30m', '1h\u00a030m', '1h 30', '30m 1h',
                      '1h 1h'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value, 'm')
        with self.assertRaisesRegex(ValueError, 'only between units'):
            parse_duration('5 m')


class DurationEdges(unittest.TestCase):
    def test_rejects_zero_negative_and_malformed(self):
        for value in ('0s', '0h0m0s', '000m', '-1s', '+5m', '1.5m', '1e3s', '1H', '5M', 'm', 's5',
                      '1h1h', '1s1m', '\u0661\u0665m', '\uff11\uff15m', '5m\n', '5 m', '\t5m',
                      '5\u00a0m', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value)

    def test_accepts_boundary_valid(self):
        for value, expected in (('1s', 1), ('0h0m1s', 1), ('007m', 420), ('1h60m', 7200),
                                ('0h5m', 300), ('100h', 360000), ('86400s', 86400)):
            with self.subTest(value=value):
                self.assertEqual(parse_duration(value), expected)

    def test_default_units_bare_numbers(self):
        self.assertEqual(parse_duration('0001', 'h'), 3600)
        with self.assertRaises(ValueError):
            parse_duration('0', 'minutes')
        with self.assertRaises(ValueError):
            parse_duration('5', 'mins')

    def test_bug_huge_duration_clean_error(self):
        """A 401-digit duration should give a clean usage error (exit 2), not a traceback."""
        result = run_cli('1' + '0' * 400 + 's')
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(result.returncode, 2, result.stderr[-300:])

    def test_bug_huge_duration_precision(self):
        """Durations past ~2**53 s lose float precision: the countdown can never tick.
        Expect parse-time rejection of absurd values (e.g. > 1 year)."""
        with self.assertRaises(ValueError):
            parse_duration('100000000000000000000h')

    def test_4301_digit_duration_is_usage_error(self):
        result = run_cli('9' * 4301 + 's')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)


class LimitsTests(unittest.TestCase):
    def test_duration_boundary_and_leading_zeros(self):
        self.assertEqual(parse_duration('8760h'), MAX_SECONDS)
        self.assertEqual(parse_duration('0' * 5000 + '1s'), 1)
        for value in ('8760h1s', str(MAX_SECONDS + 1) + 's', '9' * 5000 + 'h'):
            with self.subTest(value=value[:30]), self.assertRaisesRegex(ValueError, 'maximum is 365 days'):
                parse_duration(value)

    def test_rounds_boundary(self):
        routine = parse_pomodoro({'rounds': MAX_ROUNDS}, Pomodoro(), None, 'pomo')
        self.assertEqual(routine.rounds, MAX_ROUNDS)
        with self.assertRaises(ValueError):
            parse_pomodoro({'rounds': MAX_ROUNDS + 1}, Pomodoro(), None, 'pomo')


if __name__ == '__main__':
    unittest.main()
