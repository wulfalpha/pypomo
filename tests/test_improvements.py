"""Behavioral coverage for the reliability and usability improvements."""
import contextlib
import io
import os
import re
import signal
import subprocess
import unittest
from unittest.mock import patch

from test_edge_cases import (
    PY,
    FakeClock,
    cli_env,
    finish,
    run_cli,
    run_fake,
    shown_seconds,
)

from pypomo.cli import main
from pypomo.config import Config
from pypomo.durations import MAX_SECONDS, parse_duration
from pypomo.pomodoro import MAX_ROUNDS, Pomodoro, parse_pomodoro
from pypomo.pretty import Pretty
from pypomo.signals import Terminated
from pypomo.timer import run_timer


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
            self.assertEqual(len(output.getvalue().splitlines()), phases + 1)
            self.assertTrue(output.getvalue().endswith(f'Total: {total}\n'))

    def test_preview_custom_routine_inherits_and_counts_breaks(self):
        output = io.StringIO()
        config = Config(pomodoros={'sprint': Pomodoro(10, 2, 5, 2)})
        with patch('pypomo.cli.load_config', return_value=config), contextlib.redirect_stdout(output):
            self.assertEqual(main(['sprint.pomo', '--preview']), 0)
        self.assertIn('short break 1/2: 00:00:02', output.getvalue())
        self.assertIn('long break 2/2: 00:00:05', output.getvalue())
        self.assertTrue(output.getvalue().endswith('Total: 00:00:27\n'))

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


class DisplayTests(unittest.TestCase):
    def test_no_duplicate_initial_frame(self):
        text, _ = run_fake(3, live=True)
        self.assertEqual(shown_seconds(text), [3, 2, 1])

    def test_silent_preserves_completion_and_newline(self):
        text, _ = run_fake(2, live=True, silent=True)
        self.assertNotIn('\a', text)
        self.assertTrue(text.endswith('complete\n'))

    def test_no_color_keeps_bar_and_live_updates(self):
        with patch.dict(os.environ, {'NO_COLOR': '1', 'TERM': 'xterm'}):
            text, _ = run_fake(2, live=True, pretty=Pretty(enabled=True))
        self.assertNotRegex(text, r'\x1b\[\d+m')
        self.assertIn('\r\x1b[2K', text)
        self.assertIn('[', text)

    def test_dumb_terminal_is_plain_even_when_forced_live(self):
        with patch.dict(os.environ, {'TERM': 'dumb'}):
            text, _ = run_fake(2, live=True, pretty=Pretty(enabled=True))
        self.assertEqual(text, 'edge · 00:00:02 remaining\nedge · complete\n')

    def test_resize_recomputes_bar_and_preserves_status(self):
        widths = [80, 35, 12, 60]
        with patch('pypomo.timer.shutil.get_terminal_size',
                   side_effect=[os.terminal_size((width, 24)) for width in widths]):
            text, _ = run_fake(3, live=True, pretty=Pretty(enabled=True))
        frames = text.split('\r\x1b[2K')[1:]
        self.assertEqual(len(frames), len(widths))
        for frame, width in zip(frames, widths):
            visible = re.sub(r'\x1b\[\d+m', '', frame).rstrip('\a\n')
            self.assertLess(len(visible), width)
        self.assertIn('00:00:02 remaining', frames[1])

    def test_long_label_is_truncated_without_wrapping(self):
        output, clock = io.StringIO(), FakeClock()
        with contextlib.redirect_stdout(output), \
             patch('pypomo.timer.time.monotonic', clock.monotonic), \
             patch('pypomo.timer.time.sleep', clock.sleep), \
             patch('pypomo.timer.shutil.get_terminal_size', return_value=os.terminal_size((40, 24))):
            run_timer(1, 'a' * 200, live=True)
        frames = output.getvalue().split('\r\x1b[2K')[1:]
        self.assertTrue(all(len(frame.rstrip('\a\n')) < 40 for frame in frames))
        self.assertIn('00:00:01 remaining', frames[0])


class CancellationTests(unittest.TestCase):
    def test_handlers_restored_and_exit_code_preserved(self):
        previous = signal.getsignal(signal.SIGTERM)
        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.cli.run_timer', side_effect=Terminated(signal.SIGTERM)):
            self.assertEqual(main(['1s']), 128 + signal.SIGTERM)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_second_interrupt_during_cancellation_is_quiet(self):
        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.timer.time.sleep', side_effect=KeyboardInterrupt), \
             patch('pypomo.timer.write', side_effect=[None, KeyboardInterrupt]):
            self.assertEqual(main(['1s']), 130)

    def test_process_finish_timeout_kills_child(self):
        import sys
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                stdout=subprocess.PIPE, text=True)
        proc.first_line = ''
        with self.assertRaises(subprocess.TimeoutExpired):
            finish(proc, timeout=0.1)
        self.assertIsNotNone(proc.poll())
