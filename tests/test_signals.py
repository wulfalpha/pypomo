"""Cancellation handlers and exit statuses."""
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch

from support import disable_keyboard, finish

from pypomo.cli import main
from pypomo.config import Config
from pypomo.signals import Terminated

setUpModule = disable_keyboard


class CancellationTests(unittest.TestCase):
    def test_handlers_restored_and_exit_code_preserved(self):
        previous = signal.getsignal(signal.SIGTERM)
        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.cli.run_timer', side_effect=Terminated(signal.SIGTERM)):
            self.assertEqual(main(['1s']), 128 + signal.SIGTERM)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    @unittest.skipUnless(hasattr(signal, 'SIGUSR1'), 'needs a spare POSIX signal')
    def test_ctrl_break_cancels_on_windows(self):
        # Stand in a spare signal for Windows' SIGBREAK to check it is handled and restored.
        from pypomo.signals import cancellation_handlers
        previous = signal.getsignal(signal.SIGUSR1)
        with patch.object(signal, 'SIGBREAK', signal.SIGUSR1, create=True):
            with cancellation_handlers(), self.assertRaises(Terminated) as raised:
                signal.raise_signal(signal.SIGUSR1)
        self.assertEqual(raised.exception.signum, signal.SIGUSR1)
        self.assertEqual(signal.getsignal(signal.SIGUSR1), previous)

    def test_second_interrupt_during_cancellation_is_quiet(self):
        with patch('pypomo.cli.load_config', return_value=Config()), \
             patch('pypomo.timer.time.sleep', side_effect=KeyboardInterrupt), \
             patch('pypomo.timer.write', side_effect=[None, KeyboardInterrupt]):
            self.assertEqual(main(['1s']), 130)

    def test_process_finish_timeout_kills_child(self):
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                stdout=subprocess.PIPE, text=True)
        proc.first_line = ''
        with self.assertRaises(subprocess.TimeoutExpired):
            finish(proc, timeout=0.1)
        self.assertIsNotNone(proc.poll())


if __name__ == '__main__':
    unittest.main()
