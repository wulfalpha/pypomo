import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypomo.cli import main
from pypomo.config import Config, load_config
from pypomo.durations import parse_duration
from pypomo.timer import run_timer


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

    def test_spaced_duration(self):
        with self.assertRaisesRegex(ValueError, 'Pre-1.0.*spaces'):
            parse_duration('1h 30m')


class ConfigTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            return load_config(path)

    def test_overrides(self):
        config = self.load({'default_units': 'minutes', 'timers': {'break': '15', 'pomo': '1h30m'}})
        self.assertEqual(config.timers, {'pomo': 5400, 'break': 900})
        self.assertEqual(self.load({}).timers, {'pomo': 1500})

    def test_invalid_config(self):
        for data in ([], {'default_units': []}, {'default_units': None},
                     {'timers': []}, {'timers': {'15m': '2m'}},
                     {'timers': {'tea': 4}}, {'timers': {'tea': '0m'}}, {'typo': 1}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.load(data)

    def test_missing_and_malformed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            self.assertEqual(load_config(path).timers, {'pomo': 1500})
            with self.assertRaises(ValueError):
                load_config(path, required=True)
            path.write_text('{', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Cannot read config'):
                load_config(path)


class CliTests(unittest.TestCase):
    def test_resolution(self):
        with patch('pypomo.cli.load_config', return_value=Config('minutes', {'pomo': 1800})), \
             patch('pypomo.cli.run_timer') as timer:
            for value, seconds in [('pomo', 1800), ('15', 900), ('1h30m', 5400)]:
                self.assertEqual(main([value]), 0)
                timer.assert_called_with(seconds, value)

    def test_spaced_arguments(self):
        for args in (['1h', '30m'], ['1h 30m'], ['1h30m', '15s']):
            error = io.StringIO()
            with patch('pypomo.cli.load_config', return_value=Config()), \
                 contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                main(args)
            self.assertEqual(raised.exception.code, 2)
            self.assertIn('Pre-1.0 versions do not yet support', error.getvalue())

    def test_cancel(self):
        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.cli.run_timer', side_effect=KeyboardInterrupt), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['1s']), 130)

    def test_list_does_not_start_timer(self):
        output = io.StringIO()
        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.cli.run_timer') as timer, contextlib.redirect_stdout(output):
            self.assertEqual(main(['--list']), 0)
            timer.assert_not_called()
        self.assertIn('pomo: 00:25:00', output.getvalue())

    def test_countdown_uses_elapsed_time(self):
        output = io.StringIO()
        with patch('pypomo.timer.time.monotonic', side_effect=[100, 100, 101.7, 102.1]), \
             patch('pypomo.timer.time.sleep') as sleep, contextlib.redirect_stdout(output):
            run_timer(2, 'test')
        self.assertEqual(sleep.call_count, 2)
        self.assertAlmostEqual(sleep.call_args.args[0], 0.3)
        self.assertIn('test: done!', output.getvalue())


if __name__ == '__main__':
    unittest.main()
