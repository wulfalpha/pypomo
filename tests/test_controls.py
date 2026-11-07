"""Pause/resume key controls and waiting between Pomodoro phases."""
import contextlib
import io
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import PY, SRC, FakeClock, FakeKeys, disable_keyboard

from pypomo.cli import main
from pypomo.config import Config, load_config
from pypomo.keys import keyboard
from pypomo.pomodoro import Pomodoro, run_pomodoro
from pypomo.timer import run_timer

setUpModule = disable_keyboard


def run_with_keys(fn, events, *, live=False, stdin=None):
    clock = FakeClock()
    keys = FakeKeys(clock, events)
    out = io.StringIO()
    with patch('pypomo.timer.time.monotonic', clock.monotonic), \
         patch('pypomo.timer.time.sleep', clock.sleep), contextlib.redirect_stdout(out), \
         patch.object(sys, 'stdin', stdin if stdin is not None else sys.stdin):
        try:
            fn(keys, live)
        except KeyboardInterrupt:
            return out.getvalue(), clock, keys, True
    return out.getvalue(), clock, keys, False


class PauseTests(unittest.TestCase):
    def timer(self, seconds=5):
        return lambda keys, live: run_timer(seconds, 't', live=live, keys=keys)

    def test_pause_extends_deadline_by_paused_time(self):
        out, clock, _, cancelled = run_with_keys(self.timer(), [(2.5, 'p'), (12.5, 'p')])
        self.assertFalse(cancelled)
        self.assertAlmostEqual(clock.now, 1015.0)
        self.assertEqual(out, 't · 00:00:05 remaining\n'
                              't · paused at 00:00:03 remaining · press p to resume\n'
                              't · resumed at 00:00:03 remaining\n'
                              't · complete\n')

    def test_space_also_toggles_and_other_keys_are_ignored(self):
        out, clock, _, _ = run_with_keys(self.timer(), [(1, 'x'), (2, ' '), (3, 'x'), (4, ' ')])
        self.assertAlmostEqual(clock.now, 1007.0)
        self.assertEqual(out.count('paused at'), 1)

    def test_live_pause_stays_on_one_line_and_redraws_on_resume(self):
        out, _, _, _ = run_with_keys(self.timer(3), [(1.5, 'p'), (10, 'p')], live=True)
        self.assertEqual(out.count('\n'), 1)
        frames = out.split('\r\033[2K')[1:]
        index = next(i for i, frame in enumerate(frames) if 'paused at 00:00:02' in frame)
        self.assertEqual(frames[index + 1], 't · 00:00:02 remaining')
        self.assertNotIn('resumed', out)
        self.assertTrue(out.endswith('t · complete\a\n'))

    def test_q_cancels(self):
        out, clock, _, cancelled = run_with_keys(self.timer(), [(1.2, 'q')])
        self.assertTrue(cancelled)
        self.assertTrue(out.endswith('t · cancelled at 00:00:04 remaining\n'))

    def test_q_and_ctrl_c_while_paused_report_paused_time(self):
        for key in ('q', KeyboardInterrupt):
            with self.subTest(key=key):
                out, _, _, cancelled = run_with_keys(self.timer(), [(1.2, 'p'), (100, key)])
                self.assertTrue(cancelled)
                self.assertTrue(out.endswith('t · cancelled at 00:00:04 remaining\n'))

    def test_pretty_paused_color(self):
        config = Config()
        config.pretty.enabled = True
        out, _, _, _ = run_with_keys(
            lambda keys, live: run_timer(3, 't', live=live, keys=keys, pretty=config.pretty),
            [(1.5, 'p'), (2, 'p')], live=True)
        self.assertIn('\033[33mpaused at', out)


class WaitBetweenPhasesTests(unittest.TestCase):
    routine = Pomodoro(1, 1, 1, 2, auto_start=False)

    def run_routine(self, events=(), stdin=None, routine=None):
        return run_with_keys(
            lambda keys, live: run_pomodoro(routine or self.routine, 'r.pomo', keys=keys),
            events, stdin=stdin)

    def test_enter_starts_each_phase_after_the_first(self):
        out, _, _, cancelled = self.run_routine([(1.5 + 10 * n, '\r') for n in range(3)])
        self.assertFalse(cancelled)
        lines = out.splitlines()
        ready = [line for line in lines if 'ready' in line]
        self.assertEqual(ready, [f'r.pomo · {phase} · ready · press Enter to start'
                                 for phase in ('short break 1/2', 'focus 2/2', 'long break 2/2')])
        self.assertEqual(lines[0], 'r.pomo · focus 1/2 · 00:00:01 remaining')
        self.assertLess(lines.index(ready[0]), lines.index('r.pomo · short break 1/2 · 00:00:01 remaining'))

    def test_waiting_does_not_count_against_the_phase(self):
        _, clock, _, _ = self.run_routine([(1, 'x'), (50, '\n'), (60, '\n'), (70, '\n')])
        self.assertAlmostEqual(clock.now, 1071.0)

    def test_quit_while_waiting_cancels_routine(self):
        out, _, _, cancelled = self.run_routine([(1.5, 'p'), (5, 'q')])
        self.assertTrue(cancelled)
        self.assertTrue(out.endswith('r.pomo · short break 1/2 · cancelled before start\n'))
        self.assertNotIn('short break 1/2 · 00:00:01', out)

    def test_auto_start_routine_never_waits(self):
        out, _, keys, _ = self.run_routine(routine=Pomodoro(1, 1, 1, 2))
        self.assertNotIn('ready', out)

    def test_without_keyboard_reads_lines_from_stdin(self):
        stdin = io.StringIO('\n\n')
        out, _, _, cancelled = run_with_keys(
            lambda keys, live: run_pomodoro(self.routine, 'r.pomo'), (), stdin=stdin)
        self.assertFalse(cancelled)
        self.assertEqual(out.count('ready'), 3)
        self.assertEqual(stdin.read(), '')

    def test_exhausted_or_missing_stdin_does_not_block(self):
        for stdin, prompts in ((io.StringIO(''), 3), (None, 0)):
            with self.subTest(stdin=stdin):
                clock = FakeClock()
                out = io.StringIO()
                with patch('pypomo.timer.time.monotonic', clock.monotonic), \
                     patch('pypomo.timer.time.sleep', clock.sleep), contextlib.redirect_stdout(out), \
                     patch.object(sys, 'stdin', stdin):
                    run_pomodoro(self.routine, 'r.pomo')
                self.assertEqual(out.getvalue().count('ready'), prompts)
                self.assertIn('routine complete', out.getvalue())


class ConfigAndCliTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(data))
            return load_config(path)

    def test_auto_start_config_and_inheritance(self):
        config = self.load({'pomo': {'auto_start': False},
                            'pomodoros': {'a': {}, 'b': {'auto_start': True}}})
        self.assertFalse(config.pomo.auto_start)
        self.assertFalse(config.pomodoros['a'].auto_start)
        self.assertTrue(config.pomodoros['b'].auto_start)
        self.assertTrue(self.load({}).pomo.auto_start)
        for value in ('false', 0, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'pomo.auto_start'):
                self.load({'pomo': {'auto_start': value}})

    def test_cli_flag_overrides_routine(self):
        config = Config(pomo=Pomodoro(auto_start=False))
        with patch('pypomo.cli.load_config', return_value=config), \
             patch('pypomo.cli.run_pomodoro') as routine, patch('pypomo.cli.run_timer') as timer:
            main(['pomo'])
            self.assertFalse(routine.call_args.args[0].auto_start)
            main(['pomo', '--auto-start'])
            self.assertTrue(routine.call_args.args[0].auto_start)
            self.assertFalse(config.pomo.auto_start)  # Loaded config is not mutated.
            main(['pomo', '--no-auto-start'])
            self.assertFalse(routine.call_args.args[0].auto_start)
            self.assertEqual(main(['5m', '--no-auto-start']), 0)  # No effect on single timers.
            timer.assert_called_once()

    def test_list_marks_waiting_routines(self):
        config = Config(pomodoros={'w': Pomodoro(auto_start=False)})
        out = io.StringIO()
        with patch('pypomo.cli.load_config', return_value=config), contextlib.redirect_stdout(out):
            main(['--list'])
        self.assertIn('w.pomo: 4 focus rounds', out.getvalue())
        lines = dict(line.split(':', 1) for line in out.getvalue().splitlines())
        self.assertTrue(lines['w.pomo'].endswith(' · waits between phases'))
        self.assertNotIn('waits', lines['pomo'])

    def test_keyboard_requires_terminal_stdin(self):
        for stdin in (None, io.StringIO('p')):
            with self.subTest(stdin=stdin), patch.object(sys, 'stdin', stdin), keyboard() as keys:
                self.assertIsNone(keys)


@unittest.skipUnless(sys.platform.startswith('linux'), 'PTY tests run on Linux')
class PtyControls(unittest.TestCase):
    """Real terminal: cbreak input, pause/resume, waiting, and mode restoration."""

    def run_pty(self, args, script, timeout=20):
        """`script` is a list of (trigger text, bytes to send, delay before sending)."""
        import pty  # POSIX only; importing it at module level breaks Windows test discovery.

        env = dict(os.environ, TERM='xterm', PYTHONPATH=str(SRC), XDG_CONFIG_HOME=tempfile.mkdtemp())
        env.pop('NO_COLOR', None)
        pid, fd = pty.fork()
        if pid == 0:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.execvpe(PY, [PY, '-m', 'pypomo', *args], env)
        data, start, script = b'', time.monotonic(), list(script)
        while True:
            if script and script[0][0].encode() in data:
                _, payload, delay = script.pop(0)
                time.sleep(delay)
                os.write(fd, payload)
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
            if time.monotonic() - start > timeout:
                os.kill(pid, signal.SIGKILL)
                break
        _, status = os.waitpid(pid, 0)
        os.close(fd)
        return data.decode('utf-8', 'replace'), os.waitstatus_to_exitcode(status), time.monotonic() - start

    def test_pause_and_resume(self):
        out, code, elapsed = self.run_pty(['2s'], [('remaining', b'p', 0.3),
                                                   ('press p to resume', b'p', 1.5)])
        self.assertEqual(code, 0, repr(out[-200:]))
        self.assertIn('2s · paused at 00:00:02 remaining · press p to resume', out)
        self.assertTrue(out.endswith('2s · complete\x07\r\n'), repr(out[-60:]))
        self.assertGreaterEqual(elapsed, 3.2)
        self.assertNotIn('p\x1b', out)  # No echo of the key in cbreak mode.

    def test_q_cancels(self):
        out, code, _ = self.run_pty(['10s'], [('remaining', b'q', 0.3)])
        self.assertEqual(code, 130, repr(out[-200:]))
        self.assertRegex(out, r'cancelled at 00:00:(0\d|10) remaining\r\n$')

    def test_wait_for_enter_between_phases(self):
        with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False) as cfg:
            cfg.write('[pomodoros.t]\nfocus = "1s"\nlong_break = "1s"\nrounds = 1\n')
        self.addCleanup(os.unlink, cfg.name)
        out, code, elapsed = self.run_pty(['t.pomo', '--no-auto-start', '--config', cfg.name],
                                          [('press Enter to start', b'\r', 1.0)])
        self.assertEqual(code, 0, repr(out[-200:]))
        self.assertIn('t.pomo · long break 1/1 · ready · press Enter to start', out)
        self.assertTrue(out.endswith('routine complete\x07\r\n'), repr(out[-80:]))
        self.assertEqual(out.count('\n'), 1)
        self.assertGreaterEqual(elapsed, 3.0)

    def test_terminal_modes_restored(self):
        import pty
        import termios

        controller, terminal = pty.openpty()
        self.addCleanup(os.close, controller)
        self.addCleanup(os.close, terminal)
        before = termios.tcgetattr(terminal)
        child = subprocess.run(
            [PY, '-c', 'import sys, termios; from pypomo.keys import keyboard\n'
                       'with keyboard() as k: assert k is not None; '
                       'assert not termios.tcgetattr(0)[3] & termios.ICANON'],
            stdin=terminal, env=dict(os.environ, PYTHONPATH=str(SRC)), timeout=10,
            capture_output=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(termios.tcgetattr(terminal), before)


if __name__ == '__main__':
    unittest.main()
