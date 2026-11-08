"""Command-line parsing, timer resolution, --list, and --preview."""
import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from support import PY, FakeClock, cli_env, disable_keyboard, run_cli

from pypomo.cli import DISTRIBUTION, end_time, main
from pypomo.config import Config, load_config
from pypomo.pomodoro import Pomodoro
from pypomo.pretty import Pretty
from pypomo.timer import run_timer

setUpModule = disable_keyboard


class CliTests(unittest.TestCase):
    def test_resolution(self):
        with patch('pypomo.cli.load_config', return_value=Config('minutes', {'pomo': 1800})), \
             patch('pypomo.cli.run_timer') as timer:
            for value, seconds in [('15', 900), ('1h30m', 5400)]:
                self.assertEqual(main([value]), 0)
                timer.assert_called_with(seconds, value, live=False, pretty=Pretty(), silent=False, keys=None, on_event=None,
                                     display=True, ticks=False)

    def test_live_flag(self):
        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.cli.run_timer') as timer:
            self.assertEqual(main(['1s', '--live']), 0)
            timer.assert_called_once_with(1, '1s', live=True, pretty=Pretty(), silent=False, keys=None, on_event=None,
                                     display=True, ticks=False)

    def test_spaced_arguments(self):
        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.cli.run_timer') as timer:
            for args, seconds, label in ((['1h', '30m'], 5400, '1h 30m'), (['1h 30m'], 5400, '1h 30m'),
                                         (['1h30m', '15s'], 5415, '1h30m 15s'),
                                         (['1h', '--live', '5s'], 3605, '1h 5s')):
                with self.subTest(args=args):
                    self.assertEqual(main(args), 0)
                    self.assertEqual(timer.call_args.args, (seconds, label))
        for args, message in ((['25m', '5m'], 'once each, in order'), (['1h', 'tea'], 'unrecognized'),
                              (['tea', '5m'], 'unrecognized'), (['1h', '30'], 'unrecognized'),
                              (['1h', '-5m'], 'greater than zero')):
            error = io.StringIO()
            with self.subTest(args=args), patch('pypomo.cli.load_config', return_value=Config()), \
                 contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                main(args)
            self.assertEqual(raised.exception.code, 2)
            self.assertIn(message, error.getvalue())

    def test_spaced_preview_and_config(self):
        output = io.StringIO()
        with patch('pypomo.cli.load_config', return_value=Config()), contextlib.redirect_stdout(output):
            self.assertEqual(main(['1h', '30m', '--preview']), 0)
        self.assertTrue(output.getvalue().startswith('1h 30m: 01:30:00\nTotal: 01:30:00\nEnds: '))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('[timers]\ndeep = "1h 30m"\n[pomo]\nlong_break = "20m 30s"\n')
            config = load_config(path)
        self.assertEqual(config.timers['deep'], 5400)
        self.assertEqual(config.pomo.long_break, 1230)

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
        self.assertIn('pomo: 4 focus rounds · focus 00:25:00', output.getvalue())

    def test_countdown_uses_elapsed_time(self):
        output = io.StringIO()
        with patch('pypomo.timer.time.monotonic', side_effect=[100, 100, 101.7, 102.1]), \
             patch('pypomo.timer.time.sleep') as sleep, contextlib.redirect_stdout(output):
            run_timer(2, 'test')
        self.assertEqual(sleep.call_count, 2)
        self.assertAlmostEqual(sleep.call_args.args[0], 0.3)
        self.assertEqual(output.getvalue(), 'test · 00:00:02 remaining\ntest · complete\n')


class CliEdges(unittest.TestCase):
    def call(self, args, config=None):
        err, out = io.StringIO(), io.StringIO()
        with patch('pypomo.cli.load_config', return_value=config or Config()), \
             patch('pypomo.cli.run_timer') as timer, patch('pypomo.cli.run_pomodoro') as routine, \
             contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            try:
                code = main(args)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue(), timer, routine

    def test_usage_errors_exit_2(self):
        for args in ([], ['--list', '5m'], ['-5m'], ['--bogus'], ['5m', 'extra'], [''], ['.pomo'],
                     ['pomo.pomo'], ['5m', '--pretty=yes'], ['--l', '5m'], ['15']):
            with self.subTest(args=args):
                code, _, err, timer, routine = self.call(args)
                self.assertEqual(code, 2)
                timer.assert_not_called()
                routine.assert_not_called()

    def test_abbreviated_and_combined_flags(self):
        code, *_ , timer, _ = self.call(['5m', '--liv', '--pret'])
        self.assertEqual(code, 0)
        self.assertTrue(timer.call_args.kwargs['live'])
        self.assertTrue(timer.call_args.kwargs['pretty'].enabled)
        code, *_ , timer, _ = self.call(['5m', '--pretty', '--no-pretty'])
        self.assertFalse(timer.call_args.kwargs['pretty'].enabled)

    def test_timer_name_never_shadows_duration_syntax(self):
        cfg = Config(timers={'h': 60, 'm5': 120})
        _, _, _, timer, _ = self.call(['h'], cfg)
        self.assertEqual(timer.call_args.args, (60, 'h'))
        _, _, _, timer, _ = self.call(['5m'], cfg)
        self.assertEqual(timer.call_args.args, (300, '5m'))

    def test_version_matches_package_metadata(self):
        from importlib.metadata import PackageNotFoundError, version
        try:
            installed = version(DISTRIBUTION)
        except PackageNotFoundError:
            self.skipTest('pypomo not installed')
        code, out, *_ = self.call(['--version'])
        # Passes today only because both say 0.1.0; the string is hard-coded in cli.py
        # (see docs/review-2026-10.md, code quality).
        self.assertIn(installed, out)

    def test_help_works(self):
        result = run_cli('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--list', result.stdout)


class CommandTests(unittest.TestCase):
    def test_preview_routine_and_single_timer_never_start(self):
        for args, total, phases in ((['pomo', '--preview'], '02:10:00', 8),
                                    (['1h30m', '--preview'], '01:30:00', 1)):
            output = io.StringIO()
            with patch('pypomo.cli.load_config', return_value=Config()), \
                 patch('pypomo.cli.run_timer') as timer, \
                 patch('pypomo.cli.run_pomodoro') as routine, contextlib.redirect_stdout(output):
                self.assertEqual(main(args), 0)
            timer.assert_not_called()
            routine.assert_not_called()
            lines = output.getvalue().splitlines()
            self.assertEqual(len(lines), phases + 2)
            self.assertEqual(lines[-2], f'Total: {total}')
            self.assertRegex(lines[-1], r'^Ends: (\d{4}-\d\d-\d\d )?\d\d:\d\d if started now$')

    def test_preview_custom_routine_inherits_and_counts_breaks(self):
        output = io.StringIO()
        config = Config(pomodoros={'sprint': Pomodoro(10, 2, 5, 2)})
        with patch('pypomo.cli.load_config', return_value=config), contextlib.redirect_stdout(output):
            self.assertEqual(main(['sprint.pomo', '--preview']), 0)
        self.assertIn('short break 1/2: 00:00:02', output.getvalue())
        self.assertIn('long break 2/2: 00:00:05', output.getvalue())
        self.assertIn('\nTotal: 00:00:27\nEnds: ', output.getvalue())

    def test_end_time(self):
        now = datetime(2026, 11, 7, 14, 0, 10)
        for seconds, expected in ((1500, '14:25'), (1519, '14:25'), (1520, '14:26'),
                                  (10 * 3600, '2026-11-08 00:00'), (3 * 86400, '2026-11-10 14:00')):
            with self.subTest(seconds=seconds):
                self.assertEqual(end_time(seconds, now), expected)

    def test_preview_end_time_and_waiting_note(self):
        fixed = datetime(2026, 11, 7, 9, 0, 0)
        for args, config, expected in (
            (['pomo', '--preview'], Config(), 'Ends: 11:10 if started now'),
            (['pomo', '--preview', '--no-auto-start'], Config(),
             'Ends: 11:10 if started now, plus time waiting between phases'),
            (['pomo', '--preview', '--auto-start'], Config(pomo=Pomodoro(auto_start=False)),
             'Ends: 11:10 if started now'),
            (['2d', '--preview'], Config(), 'Ends: 2026-11-09 09:00 if started now'),
        ):
            output = io.StringIO()
            with self.subTest(args=args), patch('pypomo.cli.load_config', return_value=config), \
                 patch('pypomo.cli.datetime', wraps=datetime) as clock, contextlib.redirect_stdout(output):
                clock.now.return_value = fixed
                self.assertEqual(main(args), 0)
                self.assertEqual(output.getvalue().splitlines()[-1], expected)

    def test_unknown_name_points_to_list(self):
        result = run_cli('nonexistent')
        self.assertEqual(result.returncode, 2)
        self.assertIn('Unknown timer', result.stderr)
        self.assertIn('--list', result.stderr)

    def test_preview_requires_timer(self):
        for args in (['--preview'], ['--preview', '--list']):
            self.assertEqual(run_cli(*args).returncode, 2)

    def test_pretty_override_does_not_mutate_config(self):
        config = Config()
        with patch('pypomo.cli.load_config', return_value=config), patch('pypomo.cli.run_timer') as timer:
            main(['1s', '--pretty'])
            self.assertTrue(timer.call_args.kwargs['pretty'].enabled)
            main(['1s'])
            self.assertFalse(timer.call_args.kwargs['pretty'].enabled)
        self.assertFalse(config.pretty.enabled)

    def test_help_and_version_do_not_discover_config(self):
        for flag in ('--help', '--version'):
            with patch('pypomo.cli.default_config_path') as path, \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_:
                main([flag])
            self.assertEqual(exit_.exception.code, 0)
            path.assert_not_called()

    def test_silent_reaches_timer_and_routine(self):
        for command, target in (('1s', 'run_timer'), ('pomo', 'run_pomodoro')):
            with patch('pypomo.cli.load_config', return_value=Config()), patch('pypomo.cli.' + target) as run:
                self.assertEqual(main([command, '--silent']), 0)
                self.assertTrue(run.call_args.kwargs['silent'])

    def test_list_broken_pipe_is_handled(self):
        output = io.StringIO()
        with patch.object(output, 'write', side_effect=BrokenPipeError), \
             contextlib.redirect_stdout(output), patch('pypomo.cli.load_config', return_value=Config()):
            self.assertEqual(main(['--list']), 141)

    def test_closed_pipe_on_short_commands_has_no_shutdown_error(self):
        for args in (['--list'], ['--help'], ['--version'], ['1s'], ['pomo', '--preview']):
            with self.subTest(args=args):
                reader, writer = os.pipe()
                os.close(reader)
                try:
                    result = subprocess.run([PY, '-m', 'pypomo', *args], stdout=writer,
                                            stderr=subprocess.PIPE, env=cli_env(), timeout=5)
                finally:
                    os.close(writer)
                self.assertEqual(result.returncode, 141, result.stderr)
                self.assertEqual(result.stderr, b'')

    def test_missing_stdout_is_silent(self):
        clock = FakeClock()
        with patch('sys.stdout', None), patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.timer.time.monotonic', clock.monotonic), \
             patch('pypomo.timer.time.sleep', clock.sleep):
            self.assertEqual(main(['--list']), 0)
            self.assertEqual(main(['1s']), 0)
        self.assertEqual(clock.now, 1001)


if __name__ == '__main__':
    unittest.main()
