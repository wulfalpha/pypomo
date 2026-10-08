"""Edge-case tests for pypomo. See improvements.md for the findings behind them.

Run with the normal suite:
    PYTHONPATH=src python -m unittest discover -s tests -v

Tests named ``test_bug_*`` are regressions for the bugs recorded in improvements.md.
Real-process tests (signals, pipes, pty) use 1-5 second timers.
"""
import contextlib
import io
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pypomo import cli
from pypomo.cli import main
from pypomo.config import Config, default_config_path, load_config
from pypomo.durations import parse_duration
from pypomo.pomodoro import Pomodoro, run_pomodoro
from pypomo.pretty import Pretty, parse_pretty, render
from pypomo.timer import run_timer

# Directory containing the imported pypomo package (src/ or site-packages), so
# subprocesses run the same code as the in-process tests.
SRC = Path(cli.__file__).resolve().parents[1]
PY = sys.executable
POSIX = os.name == 'posix'
if POSIX:
    import pty
EMPTY_HOME = tempfile.TemporaryDirectory()


def cli_env(env_extra=None):
    """Environment that runs this pypomo with an empty, isolated config location."""
    env = dict(os.environ, PYTHONPATH=str(SRC), HOME=EMPTY_HOME.name,
               XDG_CONFIG_HOME=EMPTY_HOME.name, PYTHONUTF8='1')
    env.pop('PYTHONIOENCODING', None)
    env.update(env_extra or {})
    return env


def _default_sigint():
    # Children of a backgrounded shell inherit SIGINT=SIG_IGN; restore it for signal tests.
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def run_cli(*args, env_extra=None, **kw):
    """Run pypomo in a subprocess with an empty config dir."""
    return subprocess.run([PY, '-m', 'pypomo', *args], capture_output=True, encoding='utf-8', errors='replace',
                          env=cli_env(env_extra), timeout=30, **kw)


class FakeClock:
    """Monotonic clock where every sleep(x) advances by x + oversleep."""

    def __init__(self, oversleep=0.0, start=1000.0):
        self.now = start
        self.oversleep = oversleep

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0, f'sleep called with non-positive {seconds}'
        self.now += seconds + self.oversleep


def run_fake(seconds, oversleep=0.0, **kw):
    clock = FakeClock(oversleep)
    out = io.StringIO()
    with patch('pypomo.timer.time.monotonic', clock.monotonic), \
         patch('pypomo.timer.time.sleep', clock.sleep), contextlib.redirect_stdout(out):
        run_timer(seconds, 'edge', **kw)
    return out.getvalue(), clock


def shown_seconds(text):
    values = []
    for h, m, s in re.findall(r'(\d+):(\d\d):(\d\d) remaining', text):
        values.append(int(h) * 3600 + int(m) * 60 + int(s))
    return values


# --------------------------------------------------------------------------- durations
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


# --------------------------------------------------------------------------- CLI args
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
            installed = version('pypomo')
        except PackageNotFoundError:
            self.skipTest('pypomo not installed')
        code, out, *_ = self.call(['--version'])
        # Passes today only because both say 0.1.0; the string is hard-coded in cli.py
        # (see improvements.md, code quality).
        self.assertIn(installed, out)

    def test_help_works(self):
        result = run_cli('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--list', result.stdout)


# --------------------------------------------------------------------------- config
class ConfigEdges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        for p in self.dir.rglob('*'):
            with contextlib.suppress(OSError):
                p.chmod(0o700)
        self.tmp.cleanup()

    def write(self, name, content, mode='w'):
        path = self.dir / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding='utf-8')
        return path

    def test_corrupt_and_unreadable_configs_raise_valueerror(self):
        cases = {
            'a.toml': '[timers\n', 'b.json': '{"timers": ', 'c.json': '', 'd.json': '[]',
            'e.json': 'null', 'f.toml': b'\xff\xfe\x00garbage', 'g.json': '{"timers": {"tea": null}}',
            'h.toml': 'timers = 5', 'i.toml': '[pretty]\nenabled = "yes"',
            'k.yaml': 'timers: {}',
            'l.toml': '[timers]\ntea = 2024-01-01', 'm.json': '{"pomo": {"rounds": NaN}}',
        }
        for name, content in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_config(self.write(name, content))

    def test_empty_toml_is_defaults(self):
        self.assertEqual(load_config(self.write('x.toml', '')), Config())

    @unittest.skipUnless(POSIX, 'uses POSIX permission bits')
    def test_permission_denied(self):
        if os.geteuid() == 0:
            self.skipTest('root ignores permissions')
        path = self.write('p.toml', '')
        path.chmod(0)
        with self.assertRaisesRegex(ValueError, 'Cannot read config'):
            load_config(path)

    def test_directory_as_config(self):
        (self.dir / 'pypomo' / 'config.toml').mkdir(parents=True)
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.dir)}):
            with self.assertRaisesRegex(ValueError, 'Cannot read config'):
                load_config(default_config_path())

    def test_cli_missing_explicit_config_exit_2(self):
        result = run_cli('--config', str(self.dir / 'nope.toml'), '5m')
        self.assertEqual(result.returncode, 2)
        self.assertIn('not found', result.stderr)

    def test_cli_corrupt_default_config_exit_2(self):
        folder = self.dir / 'pypomo'
        folder.mkdir()
        (folder / 'config.toml').write_text('[[[')
        result = run_cli('5m', env_extra={'XDG_CONFIG_HOME': str(self.dir)})
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)

    def test_bug_utf8_bom_accepted(self):
        """Editors on Windows (Notepad, PowerShell 5 `Out-File`) write a UTF-8 BOM."""
        for name, body in (('bom.json', '{"timers": {"tea": "4m"}}'),
                           ('bom.toml', '[timers]\ntea = "4m"\n')):
            with self.subTest(name=name):
                path = self.write(name, b'\xef\xbb\xbf' + body.encode())
                try:
                    timers = load_config(path).timers
                except ValueError as exc:
                    self.fail(f'BOM-prefixed config rejected: {exc}')
                self.assertEqual(timers, {'tea': 240})

    def test_bug_relative_xdg_config_home_ignored(self):
        """XDG Base Directory spec: relative XDG_CONFIG_HOME must be ignored."""
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': 'relative/dir'}):
            self.assertTrue(default_config_path().is_absolute(), default_config_path())

    def test_json_duplicate_keys_last_wins(self):
        # Documented here as an observation: JSON silently keeps the last duplicate.
        path = self.write('dup.json', '{"timers": {"tea": "4m", "tea": "5m"}}')
        self.assertEqual(load_config(path).timers, {'tea': 300})

    def test_legacy_pomo_and_routine_named_pomo(self):
        cfg = load_config(self.write('x.toml', '[timers]\npomo = "30m"\n[pomodoros.pomo]\nrounds = 2\n'))
        self.assertEqual(cfg.pomo.focus, 1800)
        self.assertEqual(cfg.pomodoros['pomo'].rounds, 2)
        self.assertNotIn('pomo', cfg.timers)

    def test_absurd_rounds_rejected(self):
        with self.assertRaisesRegex(ValueError, 'rounds must be an integer from 1 to 1000'):
            load_config(self.write('r.toml', '[pomo]\nrounds = 99999999999999999999\n'))

    def test_default_units_applies_regardless_of_key_order(self):
        cfg = load_config(self.write('x.json', '{"timers": {"tea": "4"}, "default_units": "m"}'))
        self.assertEqual(cfg.timers['tea'], 240)

    def test_pretty_glyph_edge_cases(self):
        for ok in (' ', '#', '█', 'é'):
            parse_pretty({'bar': {'filled': ok}})
        for bad in ('\u00ad', '\u200b', '\U0001F345', 'é'.encode().decode('latin-1')[:2], '\t'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_pretty({'bar': {'empty': bad}})


# --------------------------------------------------------------------------- timer logic
class TimerLogicEdges(unittest.TestCase):
    def test_non_interactive_output_is_plain_and_two_lines(self):
        text, _ = run_fake(90, live=False, pretty=Pretty(enabled=True))
        self.assertEqual(text, 'edge · 00:01:30 remaining\nedge · complete\n')

    def test_completes_at_deadline_not_after(self):
        _, clock = run_fake(10, live=True)
        self.assertAlmostEqual(clock.now, 1010.0, places=6)

    def test_every_second_shown_with_ideal_sleep(self):
        text, _ = run_fake(120, live=True)
        self.assertEqual(sorted(set(shown_seconds(text)), reverse=True), list(range(120, 0, -1)))

    def test_bug_no_skipped_seconds_with_realistic_oversleep(self):
        """time.sleep(1) routinely overshoots (~0.1-2 ms Linux, ~1-16 ms Windows). Because the
        loop sleeps a fixed 1 s instead of to the next whole-second boundary, the error
        accumulates and the countdown visibly jumps two seconds (e.g. 00:01:05 -> 00:01:03)."""
        for oversleep in (0.002, 0.015):
            with self.subTest(oversleep=oversleep):
                text, _ = run_fake(25 * 60, oversleep=oversleep, live=True)
                shown = set(shown_seconds(text))
                missing = [s for s in range(1, 25 * 60 + 1) if s not in shown]
                self.assertEqual(missing, [], f'{len(missing)} seconds never displayed, e.g. {missing[:5]}')

    def test_wall_clock_change_ignored(self):
        clock = FakeClock()
        out = io.StringIO()
        with patch('pypomo.timer.time.monotonic', clock.monotonic), \
             patch('pypomo.timer.time.sleep', clock.sleep), \
             patch('time.time', side_effect=lambda: 0.0), contextlib.redirect_stdout(out):
            run_timer(3, 'edge', live=True)
        self.assertTrue(out.getvalue().endswith('complete\a\n'))

    def test_monotonic_jump_forward_completes_immediately(self):
        # Simulates e.g. SIGSTOP/SIGCONT or a long GC pause: no negative sleeps, finishes once.
        times = iter([0, 0, 500])
        out = io.StringIO()
        with patch('pypomo.timer.time.monotonic', lambda: next(times)), \
             patch('pypomo.timer.time.sleep') as sleep, contextlib.redirect_stdout(out):
            run_timer(10, 'edge', live=True)
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(out.getvalue().count('complete'), 1)

    def test_progress_bar_bounds(self):
        settings = Pretty(enabled=True)
        settings.colors.enabled = False
        for remaining, total in ((0, 1), (1, 1), (0.0001, 1), (10**9, 10**9), (-1, 5), (6, 5)):
            bar = re.search(r'\[(.*)\]', render('x', 's', remaining, total, settings)).group(1)
            self.assertEqual(len(bar), 20)

    def test_cancel_during_break_phase(self):
        clock = FakeClock()
        calls = {'n': 0}

        def sleep(seconds):
            calls['n'] += 1
            if calls['n'] == 3:  # focus(1s)=1 sleep, then into short break
                raise KeyboardInterrupt
            clock.sleep(seconds)

        out = io.StringIO()
        with patch('pypomo.timer.time.monotonic', clock.monotonic), \
             patch('pypomo.timer.time.sleep', sleep), contextlib.redirect_stdout(out), \
             self.assertRaises(KeyboardInterrupt):
            run_pomodoro(Pomodoro(1, 5, 5, 2), 'r.pomo', live=False)
        text = out.getvalue()
        self.assertIn('short break 1/2 · cancelled', text)
        self.assertNotIn('focus 2/2', text)

    def test_one_round_routine_and_many_rounds(self):
        self.assertEqual([p[0] for p in Pomodoro(1, 1, 1, 1).phases()], ['focus', 'long break'])
        self.assertEqual(sum(1 for _ in Pomodoro(rounds=10**5).phases()), 2 * 10**5)


# --------------------------------------------------------------------------- real processes
def spawn(*args, env_extra=None):
    """Start pypomo (stdout+stderr merged) and wait until its first status line is printed."""
    proc = subprocess.Popen([PY, '-m', 'pypomo', *args], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, encoding='utf-8', errors='replace', env=cli_env(env_extra),
                            preexec_fn=_default_sigint)
    data = b''
    deadline = time.monotonic() + 5
    try:
        while b'\n' not in data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([proc.stdout], [], [], remaining)[0]:
                raise subprocess.TimeoutExpired(proc.args, 5)
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                raise RuntimeError('Timer exited before its first status line')
            data += chunk
    except BaseException:
        proc.kill()
        proc.communicate()
        raise
    proc.first_line = data.decode('utf-8', 'replace')
    return proc


def finish(proc, timeout=20):
    """Return everything the process printed, after it exits."""
    try:
        rest, _ = proc.communicate(timeout=timeout)
        return proc.first_line + rest
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


@unittest.skipUnless(POSIX, 'uses POSIX signals, bash and head')
class ProcessEdges(unittest.TestCase):
    def test_real_one_second_timer(self):
        start = time.monotonic()
        result = run_cli('1s')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '1s · 00:00:01 remaining\n1s · complete\n')
        self.assertLess(time.monotonic() - start, 5)

    def test_sigint_exit_130_with_cancel_line(self):
        proc = spawn('10s')
        proc.send_signal(signal.SIGINT)
        out = finish(proc)
        self.assertEqual(proc.returncode, 130, out)
        self.assertIn('cancelled at', out)
        self.assertNotIn('Traceback', out)

    def test_bug_sigterm_reports_cancellation(self):
        """`timeout`, `kill`, systemd, tmux kill-pane and closing a terminal send SIGTERM/SIGHUP.
        pypomo dies without writing a cancellation line (and leaves a live line unterminated)."""
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sig=sig.name):
                proc = spawn('10s')
                proc.send_signal(sig)
                out = finish(proc)
                self.assertIn('cancelled at', out)
                self.assertEqual(proc.returncode, 128 + sig, out)
                self.assertNotIn('Traceback', out)

    def test_suspend_resume_counts_stopped_time(self):
        # Observation (not a bug per README): Ctrl-Z does not pause; stopped time still counts.
        proc = spawn('3s')
        proc.send_signal(signal.SIGSTOP)
        time.sleep(3.5)
        resumed = time.monotonic()
        proc.send_signal(signal.SIGCONT)
        out = finish(proc)
        self.assertLess(time.monotonic() - resumed, 2)
        self.assertIn('complete', out)

    def _broken_pipe(self, *args):
        cmd = f'{shlex.quote(PY)} -m pypomo {" ".join(args)} | head -c 10 >/dev/null'
        return subprocess.run(['bash', '-o', 'pipefail', '-c', cmd], capture_output=True, encoding='utf-8', errors='replace',
                              env=cli_env(), timeout=30)

    def test_bug_broken_pipe_no_traceback(self):
        for args in (('2s',), ('3s', '--live')):
            with self.subTest(args=args):
                result = self._broken_pipe(*args)
                self.assertEqual(result.returncode, 141, result.stderr)
                self.assertEqual(result.stderr, '')

    def test_bug_closed_stdout_no_traceback(self):
        result = subprocess.run(['bash', '-c', f'{shlex.quote(PY)} -m pypomo 1s >&-'],
                                capture_output=True, encoding='utf-8', errors='replace', env=cli_env(), timeout=30)
        self.assertNotIn('Traceback', result.stderr, result.stderr[-300:])

    def test_concurrent_instances_independent(self):
        procs = [spawn('1s') for _ in range(5)]
        for p in procs:
            out = finish(p)
            self.assertEqual(p.returncode, 0)
            self.assertTrue(out.endswith('complete\n'), out)

    def test_list_with_closed_stdin_and_no_home_config(self):
        # Empty XDG_CONFIG_HOME falls back to $HOME/.config (an empty temp dir here).
        result = run_cli('--list', stdin=subprocess.DEVNULL, env_extra={'XDG_CONFIG_HOME': ''})
        self.assertEqual(result.returncode, 0)


class EncodingEdges(unittest.TestCase):
    def test_bug_non_utf8_stdout(self):
        """Plain output contains U+00B7 '·'; pretty bar uses U+2588/U+2591. On an ASCII or
        legacy code-page stdout (e.g. Windows redirect, PYTHONIOENCODING, some CI) it crashes."""
        for enc, args in (('ascii', ('1s',)), ('cp1252', ('1s', '--live', '--pretty')),
                          ('ascii', ('--list',)), ('ascii', ('pomo', '--preview'))):
            with self.subTest(enc=enc, args=args):
                result = run_cli(*args, env_extra={'PYTHONIOENCODING': enc, 'PYTHONUTF8': '0'})
                self.assertNotIn('Traceback', result.stderr, result.stderr[-300:])
                self.assertEqual(result.returncode, 0)


@unittest.skipUnless(sys.platform.startswith('linux'),
                     'pty end-of-output and Ctrl-C handling only verified on Linux')
class PtyEdges(unittest.TestCase):
    """Runs pypomo inside a real pseudo-terminal (isatty() == True)."""

    def run_pty(self, args, ctrl_c=False, env_extra=None, timeout=20):
        env = cli_env(dict({'TERM': 'xterm'}, **(env_extra or {})))
        pid, fd = pty.fork()
        if pid == 0:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.execvpe(PY, [PY, '-m', 'pypomo', *args], env)
        data, start, sent = b'', time.monotonic(), False
        while True:
            # Send Ctrl-C once the countdown has started (first status line drawn).
            if ctrl_c and not sent and b'remaining' in data:
                time.sleep(0.3)
                os.write(fd, b'\x03')
                sent = True
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
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
        return data.decode('utf-8', 'replace'), os.waitstatus_to_exitcode(status)

    def test_tty_single_line_and_bell(self):
        out, code = self.run_pty(['2s'])
        self.assertEqual(code, 0)
        self.assertIn('\r\x1b[2K2s · 00:00:01 remaining', out)
        self.assertTrue(out.endswith('2s · complete\x07\r\n'), repr(out[-60:]))
        self.assertEqual(out.count('\n'), 1)

    def test_tty_ctrl_c(self):
        out, code = self.run_pty(['10s'], ctrl_c=True)
        self.assertEqual(code, 130, repr(out[-200:]))
        self.assertRegex(out, r'cancelled at 00:00:(0\d|10) remaining')
        self.assertNotIn('Traceback', out)

    def test_tty_pretty_routine_phase_change(self):
        cfg = tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False)
        cfg.write('[pomodoros.t]\nfocus = "1s"\nshort_break = "1s"\nlong_break = "1s"\nrounds = 1\n')
        cfg.close()
        out, code = self.run_pty(['t.pomo', '--pretty', '--config', cfg.name])
        os.unlink(cfg.name)
        self.assertEqual(code, 0)
        self.assertIn('focus 1/1', out)
        self.assertIn('long break 1/1', out)
        self.assertEqual(out.count('\n'), 1)
        self.assertTrue(out.rstrip().endswith('\x1b[0m\x07') or 'routine complete' in out)


if __name__ == '__main__':
    unittest.main()
