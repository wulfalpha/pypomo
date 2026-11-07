"""Countdown timing and display, using fake clocks."""
import contextlib
import io
import os
import re
import unittest
from unittest.mock import patch

from support import FakeClock, disable_keyboard, run_fake, shown_seconds

from pypomo.cli import main
from pypomo.config import Config
from pypomo.pomodoro import Pomodoro, run_pomodoro
from pypomo.pretty import Pretty, render
from pypomo.timer import run_timer

setUpModule = disable_keyboard


class DisplayTests(unittest.TestCase):
    def test_live_completion(self):
        for force_live, tty in ((True, False), (False, True)):
            with self.subTest(force_live=force_live, tty=tty):
                output = io.StringIO()
                with patch.object(output, 'isatty', return_value=tty), \
                     patch('pypomo.timer.time.monotonic', side_effect=[100, 100, 101, 102]), \
                     patch('pypomo.timer.time.sleep'), contextlib.redirect_stdout(output):
                    run_timer(2, 'pomo', live=force_live)
                text = output.getvalue()
                self.assertEqual(text.count('\n'), 1)
                self.assertIn('\r\033[2Kpomo · 00:00:01 remaining', text)
                self.assertTrue(text.endswith('\r\033[2Kpomo · complete\a\n'))
                self.assertTrue(all(frame.startswith('pomo · ') for frame in text.split('\r\033[2K')[1:]))

    def test_cancel_redraws_and_ends_line(self):
        for live in (True, False):
            with self.subTest(live=live):
                output = io.StringIO()
                with patch('pypomo.cli.load_config', return_value=Config()), \
                     patch('pypomo.timer.time.monotonic', side_effect=[100, 100, 101.2]), \
                     patch('pypomo.timer.time.sleep', side_effect=KeyboardInterrupt), \
                     contextlib.redirect_stdout(output):
                    self.assertEqual(main(['5s'] + (['--live'] if live else [])), 130)
                text = output.getvalue()
                self.assertTrue(text.endswith('5s · cancelled at 00:00:04 remaining\n'))
                self.assertEqual(text.count('\n'), 1 if live else 2)
                self.assertNotIn('complete', text)
                self.assertNotIn('\a', text)
                if not live:
                    self.assertNotIn('\r', text)
                    self.assertNotIn('\033', text)


class DisplayOptionTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
