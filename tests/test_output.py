"""Windows CRT pipe errors must be handled without hiding unrelated failures."""
import contextlib
import errno
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from pypomo.cli import main
from pypomo.config import Config
from pypomo.output import flush, write


class WindowsPipeTests(unittest.TestCase):
    def setUp(self):
        reader, self.writer = os.pipe()
        os.close(reader)
        self.addCleanup(os.close, self.writer)

    def test_windows_pipe_write_and_flush_exit_quietly(self):
        for operation in ('write', 'flush'):
            for args in (['--list'], ['--help'], ['--version'], ['1s'], ['pomo', '--preview']):
                with self.subTest(operation=operation, args=args):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output), \
                         patch.object(output, 'fileno', return_value=self.writer), \
                         patch.object(output, operation, side_effect=OSError(errno.EINVAL, 'Invalid argument')), \
                         patch('pypomo.output.sys.platform', 'win32'), \
                         patch('pypomo.cli.version', return_value='0.1.0'), \
                         patch('pypomo.cli.load_config', return_value=Config()), \
                         patch('pypomo.cli.silence_broken_pipe') as silence:
                        self.assertEqual(main(args), 141)
                        silence.assert_called_once_with()

    def test_unrelated_output_errors_propagate(self):
        with tempfile.TemporaryFile() as regular:
            cases = [('win32', errno.EINVAL, regular.fileno()),
                     ('linux', errno.EINVAL, self.writer),
                     ('win32', errno.ENOSPC, self.writer)]
            for platform, number, descriptor in cases:
                for operation, call in (('write', lambda: write('status')), ('flush', flush)):
                    with self.subTest(platform=platform, number=number, operation=operation):
                        output = io.StringIO()
                        error = OSError(number, 'unrelated output failure')
                        with contextlib.redirect_stdout(output), \
                             patch.object(output, 'fileno', return_value=descriptor), \
                             patch.object(output, operation, side_effect=error), \
                             patch('pypomo.output.sys.platform', platform), \
                             self.assertRaises(OSError) as raised:
                            call()
                        self.assertIs(raised.exception, error)

    def test_einval_without_a_descriptor_propagates(self):
        output = io.StringIO()
        error = OSError(errno.EINVAL, 'Invalid argument')
        with contextlib.redirect_stdout(output), \
             patch.object(output, 'write', side_effect=error), \
             patch('pypomo.output.sys.platform', 'win32'), self.assertRaises(OSError) as raised:
            write('status')
        self.assertIs(raised.exception, error)

    def test_non_output_einval_is_not_treated_as_a_broken_pipe(self):
        output = io.StringIO()
        error = OSError(errno.EINVAL, 'unrelated CLI failure')
        with contextlib.redirect_stdout(output), \
             patch.object(output, 'fileno', return_value=self.writer), \
             patch('pypomo.output.sys.platform', 'win32'), \
             patch('pypomo.cli._main', side_effect=error), \
             patch('pypomo.cli.silence_broken_pipe') as silence, self.assertRaises(OSError) as raised:
            main(['1s'])
        self.assertIs(raised.exception, error)
        silence.assert_not_called()
