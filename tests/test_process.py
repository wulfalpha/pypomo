"""End-to-end runs in real processes and pseudo-terminals.

Tests named ``test_bug_*`` are regressions for bugs recorded in
docs/review-2026-10.md. They use 1-5 second timers.
"""
import os
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from support import POSIX, PY, cli_env, disable_keyboard, finish, run_cli, spawn

if POSIX:
    import pty

setUpModule = disable_keyboard


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
