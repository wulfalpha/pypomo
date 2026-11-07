"""Event records and --format jsonl output."""
import contextlib
import io
import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from support import POSIX, PY, FakeClock, cli_env, disable_keyboard

from pypomo.cli import main
from pypomo.config import Config
from pypomo.events import Events, JsonLines, Phase, event_record
from pypomo.pomodoro import Pomodoro

setUpModule = disable_keyboard

FIELDS = ['event', 'timer', 'label', 'phase', 'round', 'rounds', 'duration', 'remaining', 'last', 'time']


def run_main(args, config=None, stdin=None):
    clock, out, err = FakeClock(), io.StringIO(), io.StringIO()
    with patch('pypomo.cli.load_config', return_value=config or Config()), \
         patch('pypomo.timer.time.monotonic', clock.monotonic), \
         patch('pypomo.timer.time.sleep', clock.sleep), \
         patch.object(sys, 'stdin', stdin if stdin is not None else io.StringIO('')), \
         contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(args)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class RecordTests(unittest.TestCase):
    def test_routine_phase_record(self):
        now = datetime(2026, 11, 7, 14, 25, 0, tzinfo=timezone(timedelta(hours=-5)))
        record = event_record('end', 'sprint.pomo', Phase('sprint.pomo · focus 1/3', 'focus', 900, 1, 3, False),
                              0, now)
        self.assertEqual(list(record), FIELDS)
        self.assertEqual(record, {'event': 'end', 'timer': 'sprint.pomo', 'label': 'sprint.pomo · focus 1/3',
                                  'phase': 'focus', 'round': 1, 'rounds': 3, 'duration': 900,
                                  'remaining': 0, 'last': False, 'time': '2026-11-07T14:25:00-05:00'})

    def test_single_timer_record_and_ascii_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            JsonLines('25m')('start', Phase('25m', 'timer', 1500), 1500)
        line = out.getvalue()
        self.assertTrue(line.endswith('}\n'))
        self.assertTrue(line.isascii())
        record = json.loads(line)
        self.assertEqual((record['phase'], record['round'], record['rounds'], record['last']),
                         ('timer', None, None, True))
        datetime.fromisoformat(record['time'])

    def test_events_fan_out_to_every_listener_in_order(self):
        calls = []
        events = Events([lambda *a: calls.append(('a', a[0])), lambda *a: calls.append(('b', a[0]))])
        events.handler(Phase('t', 'timer', 1))('start', 1)
        self.assertEqual(calls, [('a', 'start'), ('b', 'start')])
        self.assertFalse(Events([]))


class FormatTests(unittest.TestCase):
    def test_single_timer_emits_only_json(self):
        code, out, err = run_main(['2s', '--format', 'jsonl'])
        self.assertEqual((code, err), (0, ''))
        records = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([(r['event'], r['remaining']) for r in records], [('start', 2), ('end', 0)])
        self.assertNotIn('remaining', out.replace('"remaining"', ''))
        self.assertNotIn('\a', out)
        self.assertNotIn('\r', out)

    def test_routine_with_waiting_emits_wait_and_no_prompt(self):
        config = Config(pomodoros={'t': Pomodoro(1, 1, 1, 2, auto_start=False)})
        code, out, _ = run_main(['t.pomo', '--format', 'jsonl', '--pretty'], config, io.StringIO('\n\n\n'))
        self.assertEqual(code, 0)
        self.assertNotIn('ready', out)
        records = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([(r['event'], r['phase'], r['round']) for r in records], [
            ('start', 'focus', 1), ('end', 'focus', 1),
            ('wait', 'short_break', 1), ('start', 'short_break', 1), ('end', 'short_break', 1),
            ('wait', 'focus', 2), ('start', 'focus', 2), ('end', 'focus', 2),
            ('wait', 'long_break', 2), ('start', 'long_break', 2), ('end', 'long_break', 2)])
        self.assertEqual([r['last'] for r in records][-1], True)

    def test_cancel_is_the_last_record(self):
        clock, out = FakeClock(), io.StringIO()
        sleeps = iter([None, KeyboardInterrupt])

        def sleep(seconds):
            if next(sleeps) is KeyboardInterrupt:
                raise KeyboardInterrupt
            clock.sleep(seconds)

        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.timer.time.monotonic', clock.monotonic), \
             patch('pypomo.timer.time.sleep', sleep), contextlib.redirect_stdout(out):
            self.assertEqual(main(['5s', '--format', 'jsonl']), 130)
        records = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([(r['event'], r['remaining']) for r in records], [('start', 5), ('cancel', 4)])

    def test_hooks_and_jsonl_both_receive_events(self):
        with patch('pypomo.hooks.HookRunner.emit') as emit:
            code, out, _ = run_main(['1s', '--format', 'jsonl'], Config(hooks={'end': ['true']}))
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 2)
        self.assertEqual([call.args[0] for call in emit.call_args_list], ['start', 'end'])

    def test_text_is_the_default_and_unchanged(self):
        _, out, _ = run_main(['1s'])
        self.assertEqual(out, '1s · 00:00:01 remaining\n1s · complete\n')
        _, explicit, _ = run_main(['1s', '--format', 'text'])
        self.assertEqual(explicit, out)

    def test_incompatible_flags(self):
        for args in (['--list', '--format', 'jsonl'], ['5m', '--preview', '--format', 'jsonl'],
                     ['5m', '--live', '--format', 'jsonl'], ['5m', '--format', 'json']):
            with self.subTest(args=args):
                code, out, err = run_main(args)
                self.assertEqual(code, 2)
                self.assertEqual(out, '')
                self.assertTrue('--format jsonl is for running timers' in err or 'invalid choice' in err, err)


class ProcessTests(unittest.TestCase):
    def test_real_process_output_parses_line_by_line(self):
        result = subprocess.run([PY, '-m', 'pypomo', '1s', '--format', 'jsonl'], capture_output=True,
                                encoding='utf-8', env=cli_env(), timeout=30)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual([json.loads(line)['event'] for line in result.stdout.splitlines()], ['start', 'end'])

    @unittest.skipUnless(POSIX, 'uses a shell pipeline')
    def test_reader_exiting_early_is_quiet(self):
        result = subprocess.run(['bash', '-c', f'"{PY}" -m pypomo 3s --format jsonl | head -n 1; '
                                               'echo "status=${PIPESTATUS[0]}"'],
                                capture_output=True, encoding='utf-8', env=cli_env(), timeout=30)
        lines = result.stdout.splitlines()
        self.assertEqual(json.loads(lines[0])['event'], 'start')
        self.assertEqual(lines[-1], 'status=141')
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
