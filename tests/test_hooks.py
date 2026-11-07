"""Event hooks: validation, event sequence, environment, and real processes."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import SRC, FakeClock, FakeKeys, disable_keyboard

from pypomo.cli import main
from pypomo.config import Config, load_config
from pypomo.events import Events, Phase
from pypomo.hooks import HookRunner, parse_hooks
from pypomo.pomodoro import Pomodoro, run_pomodoro
from pypomo.timer import run_timer

setUpModule = disable_keyboard


class ParseTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_hooks({'end': 'notify-send done', 'any': ['logger', '-t', 'pypomo']}),
                         {'end': ['notify-send done'], 'any': [['logger', '-t', 'pypomo']]})
        self.assertEqual(parse_hooks({}), {})

    def test_invalid(self):
        for data, message in (([], 'hooks must be'), ({'finish': 'x'}, 'Unknown hooks: finish'),
                              ({'end': ''}, 'hooks.end'), ({'end': '   '}, 'hooks.end'),
                              ({'end': []}, 'hooks.end'), ({'end': ['']}, 'hooks.end'),
                              ({'end': ['ls', 1]}, 'hooks.end'), ({'start': 5}, 'hooks.start'),
                              ({'any': None}, 'hooks.any')):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, message):
                parse_hooks(data)

    def test_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('[hooks]\nend = "notify-send done"\npause = ["true"]\n')
            self.assertEqual(load_config(path).hooks, {'end': ['notify-send done'], 'pause': [['true']]})
            path.write_text('[hooks]\nfinish = "x"\n')
            with self.assertRaisesRegex(ValueError, 'Unknown hooks'):
                load_config(path)


class EventSequenceTests(unittest.TestCase):
    def run(self, result=None):
        with contextlib.redirect_stdout(io.StringIO()):
            super().run(result)

    def record(self, fn, events=()):
        clock, seen = FakeClock(), []
        keys = FakeKeys(clock, events) if events else None
        with patch('pypomo.timer.time.monotonic', clock.monotonic), \
             patch('pypomo.timer.time.sleep', clock.sleep):
            try:
                fn(keys, lambda event, remaining: seen.append((event, remaining)))
            except KeyboardInterrupt:
                seen.append('interrupted')
        return seen

    def test_start_pause_resume_end(self):
        seen = self.record(lambda keys, on: run_timer(5, 't', keys=keys, on_event=on),
                           [(1.5, 'p'), (9, 'p')])
        self.assertEqual(seen, [('start', 5), ('pause', 4), ('resume', 4), ('end', 0)])

    def test_cancel(self):
        seen = self.record(lambda keys, on: run_timer(5, 't', keys=keys, on_event=on), [(2.2, 'q')])
        self.assertEqual(seen, [('start', 5), ('cancel', 3), 'interrupted'])

    def test_ctrl_c_while_paused(self):
        seen = self.record(lambda keys, on: run_timer(5, 't', keys=keys, on_event=on),
                           [(1.5, 'p'), (9, KeyboardInterrupt)])
        self.assertEqual(seen, [('start', 5), ('pause', 4), ('cancel', 4), 'interrupted'])

    def test_wait_event_precedes_each_waiting_phase(self):
        calls = []
        runner = HookRunner({'any': ['x']}, 'r.pomo')
        runner.emit = lambda event, phase, remaining: calls.append((event, phase.phase, remaining, phase.last))
        self.record(lambda keys, on: run_pomodoro(Pomodoro(1, 1, 3, 1, auto_start=False), 'r.pomo',
                                                  keys=keys, events=Events([runner])), [(1.5, '\r')])
        self.assertEqual(calls, [('start', 'focus', 1, False), ('end', 'focus', 0, False),
                                 ('wait', 'long_break', 3, True), ('start', 'long_break', 3, True),
                                 ('end', 'long_break', 0, True)])

    def test_quitting_while_waiting_sends_cancel(self):
        calls = []
        events = Events([lambda event, phase, remaining: calls.append((event, phase.phase, remaining))])
        seen = self.record(lambda keys, on: run_pomodoro(Pomodoro(1, 2, 3, 2, auto_start=False), 'r.pomo',
                                                         keys=keys, events=events), [(1.5, 'q')])
        self.assertEqual(seen, ['interrupted'])
        self.assertEqual(calls, [('start', 'focus', 1), ('end', 'focus', 0), ('wait', 'short_break', 2),
                                 ('cancel', 'short_break', 2)])


class RunnerTests(unittest.TestCase):
    def emit(self, commands, event='end', phase=None, remaining=0):
        runner = HookRunner(commands, 'sprint.pomo')
        with patch('pypomo.hooks.subprocess.Popen') as popen:
            runner.emit(event, phase or Phase('sprint.pomo · short break 1/3', 'short_break', 180, 1, 3, False),
                        remaining)
        return popen

    def test_environment_and_process_options(self):
        popen = self.emit({'end': ['notify-send done'], 'any': [['logger', 'x']]}, remaining=0)
        self.assertEqual([call.args[0] for call in popen.call_args_list], ['notify-send done', ['logger', 'x']])
        shell_call, argv_call = popen.call_args_list
        self.assertTrue(shell_call.kwargs['shell'])
        self.assertFalse(argv_call.kwargs['shell'])
        env = shell_call.kwargs['env']
        self.assertEqual({key: value for key, value in env.items() if key.startswith('PYPOMO_')}, {
            'PYPOMO_EVENT': 'end', 'PYPOMO_TIMER': 'sprint.pomo',
            'PYPOMO_LABEL': 'sprint.pomo · short break 1/3', 'PYPOMO_PHASE': 'short_break',
            'PYPOMO_ROUND': '1', 'PYPOMO_ROUNDS': '3', 'PYPOMO_DURATION': '180',
            'PYPOMO_REMAINING': '0', 'PYPOMO_LAST': '0'})
        self.assertEqual(env.get('PATH'), os.environ.get('PATH'))
        self.assertEqual(shell_call.kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(shell_call.kwargs['stdout'], subprocess.DEVNULL)
        self.assertNotIn('stderr', shell_call.kwargs)
        if sys.platform != 'win32':
            self.assertTrue(shell_call.kwargs['start_new_session'])

    def test_single_timer_environment(self):
        popen = self.emit({'start': ['x']}, event='start', phase=Phase('25m', 'timer', 1500), remaining=1500)
        env = popen.call_args.kwargs['env']
        self.assertEqual((env['PYPOMO_PHASE'], env['PYPOMO_ROUND'], env['PYPOMO_ROUNDS'], env['PYPOMO_LAST']),
                         ('timer', '', '', '1'))

    def test_only_matching_events_run(self):
        self.assertFalse(self.emit({'start': ['x']}, event='end').called)
        self.assertFalse(HookRunner({'end': []}, 't'))

    def test_launch_failure_warns_once_and_never_raises(self):
        runner = HookRunner({'any': [['/nonexistent/pypomo-hook']]}, 't')
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            for event in ('start', 'end'):
                runner.emit(event, Phase('t', 'timer', 1), 0)
        self.assertEqual(error.getvalue().count('hook could not start: /nonexistent/pypomo-hook'), 1)


class CliTests(unittest.TestCase):
    def hooks_for(self, args, config_hooks=None):
        config = Config(hooks=config_hooks or {})
        with patch('pypomo.cli.load_config', return_value=config), \
             patch('pypomo.cli.run_timer') as timer, patch('pypomo.cli.run_pomodoro') as routine, \
             patch('pypomo.cli.HookRunner', wraps=HookRunner) as runner:
            self.assertEqual(main(args), 0)
        return runner, timer, routine

    def test_no_hooks_means_no_runner(self):
        runner, timer, _ = self.hooks_for(['5m'])
        runner.assert_not_called()
        self.assertIsNone(timer.call_args.kwargs['on_event'])

    def test_flag_adds_to_config_any(self):
        runner, timer, _ = self.hooks_for(['5m', '--hook', 'a', '--hook', 'b'], {'any': ['c'], 'end': ['d']})
        self.assertEqual(runner.call_args.args, ({'any': ['c', 'a', 'b'], 'end': ['d']}, '5m'))
        self.assertIsNotNone(timer.call_args.kwargs['on_event'])

    def test_no_hooks_flag_ignores_config_but_keeps_flag(self):
        runner, _, routine = self.hooks_for(['pomo', '--no-hooks'], {'end': ['d']})
        runner.assert_not_called()
        self.assertIsNone(routine.call_args.kwargs['events'])
        runner, _, routine = self.hooks_for(['pomo', '--no-hooks', '--hook', 'a'], {'end': ['d']})
        self.assertEqual(runner.call_args.args, ({'any': ['a']}, 'pomo'))

    def test_preview_and_list_run_no_hooks(self):
        with patch('pypomo.cli.load_config', return_value=Config(hooks={'any': ['x']})), \
             patch('pypomo.hooks.subprocess.Popen') as popen, contextlib.redirect_stdout(io.StringIO()):
            main(['5m', '--preview'])
            main(['--list'])
        popen.assert_not_called()


class ProcessTests(unittest.TestCase):
    """Real hooks launched by a real pypomo process."""

    def run_cli(self, args, config):
        directory = Path(tempfile.mkdtemp())
        log = directory / 'events.log'
        path = directory / 'config.toml'
        path.write_text(config.replace('LOG', log.as_posix()), encoding='utf-8')
        env = dict(os.environ, PYTHONPATH=str(SRC), XDG_CONFIG_HOME=str(directory))
        args = [arg.replace('LOG', log.as_posix()) for arg in args]
        result = subprocess.run([sys.executable, '-m', 'pypomo', *args, '--config', str(path)],
                                capture_output=True, text=True, env=env, timeout=30)
        return result, log

    def wait_for_lines(self, log, count):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if log.exists() and len(log.read_text().splitlines()) >= count:
                break
            time.sleep(0.05)
        return sorted(log.read_text().splitlines()) if log.exists() else []

    def test_argv_hook_receives_events(self):
        # Hooks for consecutive events overlap, so each writes its own file rather than
        # appending to a shared log (concurrent appends can interleave on Windows).
        script = ("import os; e = os.environ; open(r'LOG.' + e['PYPOMO_EVENT'] + '-' + e['PYPOMO_PHASE']"
                  " + '-' + e['PYPOMO_LAST'], 'w').close()")
        exe = sys.executable.replace('\\', '/')
        result, log = self.run_cli(['t.pomo'], f"[hooks]\nany = ['{exe}', '-c', \"{script}\"]\n"
                                               '[pomodoros.t]\nfocus = "1s"\nlong_break = "1s"\nrounds = 1\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = sorted(['start-focus-0', 'end-focus-0', 'start-long_break-1', 'end-long_break-1'])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            seen = sorted(path.name.removeprefix(log.name + '.') for path in log.parent.glob(log.name + '.*'))
            if len(seen) >= len(expected):
                break
            time.sleep(0.05)
        self.assertEqual(seen, expected)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX shell syntax')
    def test_shell_hook_and_failing_hook_do_not_affect_exit(self):
        result, log = self.run_cli(['1s', '--hook', 'echo "$PYPOMO_EVENT $PYPOMO_TIMER" >> LOG; exit 3'],
                                   '[hooks]\nend = ["/nonexistent/pypomo-hook"]\n')
        log_lines = self.wait_for_lines(log, 2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log_lines, ['end 1s', 'start 1s'])
        self.assertIn('hook could not start: /nonexistent/pypomo-hook', result.stderr)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
