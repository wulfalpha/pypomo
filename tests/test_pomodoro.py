import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypomo.cli import main
from pypomo.config import Config, load_config
from pypomo.pomodoro import Pomodoro, run_pomodoro


class PomodoroTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(data))
            return load_config(path)

    def test_inheritance_and_legacy(self):
        config = self.load({'timers': {'pomo': '30m', 'tea': '4m'},
                            'pomo': {'short_break': '2m'},
                            'pomodoros': {'sprint': {'focus': '10m', 'rounds': 2}}})
        self.assertEqual(config.pomo, Pomodoro(1800, 120, 900, 4))
        self.assertEqual(config.pomodoros['sprint'], Pomodoro(600, 120, 900, 2))
        self.assertEqual(config.timers, {'tea': 240})
        config = self.load({'timers': {'pomo': '30m'}, 'pomo': {'focus': '20m'}})
        self.assertEqual(config.pomo.focus, 1200)

    def test_invalid_settings(self):
        for data in ({'pomo': []}, {'pomodoros': []}, {'pomodoros': {'bad.name': {}}},
                     {'pomo': {'rounds': True}}, {'pomo': {'rounds': 0}},
                     {'pomo': {'rounds': 1.5}}, {'pomo': {'rounds': '4'}},
                     {'pomo': {'focus': '0m'}}, {'pomo': {'focus': 25}},
                     {'pomo': {'typo': '5m'}}, {'pomodoros': {'sprint': {'focus': '-1s'}}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.load(data)

    def test_phase_order(self):
        self.assertEqual(list(Pomodoro(10, 2, 5, 2).phases()),
                         [('focus', 10, 1), ('short break', 2, 1), ('focus', 10, 2), ('long break', 5, 2)])
        self.assertEqual(list(Pomodoro(rounds=1).phases()), [('focus', 1500, 1), ('long break', 900, 1)])

    def test_resolution_and_listing(self):
        config = Config(pomodoros={'sprint': Pomodoro(rounds=2)}, timers={'sprint': 60})
        with patch('pypomo.cli.load_config', return_value=config), \
             patch('pypomo.cli.run_pomodoro') as routine, patch('pypomo.cli.run_timer') as timer:
            main(['pomo'])
            self.assertEqual(routine.call_args.args, (config.pomo, 'pomo'))
            main(['sprint.pomo'])
            self.assertEqual(routine.call_args.args, (config.pomodoros['sprint'], 'sprint.pomo'))
            main(['sprint'])
            self.assertEqual(timer.call_args.args, (60, 'sprint'))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(['--list'])
            self.assertIn('sprint.pomo: 2 focus rounds', output.getvalue())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main(['missing.pomo'])
            self.assertEqual(raised.exception.code, 2)

    def test_entire_routine_keeps_one_line(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
             patch('pypomo.timer.time.monotonic', side_effect=[0, 1, 1, 2, 2, 3, 3, 4]):
            run_pomodoro(Pomodoro(1, 1, 1, 2), 'sprint.pomo', live=True)
        text = output.getvalue()
        self.assertEqual(text.count('\n'), 1)
        self.assertIn('focus 1/2', text)
        self.assertIn('short break 1/2', text)
        self.assertIn('focus 2/2', text)
        self.assertTrue(text.endswith('long break 2/2 · routine complete\a\n'))

    def test_cancel_stops_routine(self):
        output = io.StringIO()
        with patch('pypomo.cli.load_config', return_value=Config()), \
             contextlib.redirect_stdout(output), \
             patch('pypomo.timer.time.monotonic', side_effect=[0, 0, 1]), \
             patch('pypomo.timer.time.sleep', side_effect=KeyboardInterrupt):
            self.assertEqual(main(['pomo', '--live']), 130)
        self.assertIn('focus 1/4 · cancelled', output.getvalue())
        self.assertNotIn('break', output.getvalue())
        self.assertEqual(output.getvalue().count('\n'), 1)

    def test_toml_routines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('default_units = "minutes"\n[pomo]\nfocus = "20"\n'
                            '[pomodoros.sprint]\nrounds = 2\nshort_break = "1m30s"\n')
            config = load_config(path)
            self.assertEqual(config.pomodoros['sprint'], Pomodoro(1200, 90, 900, 2))
