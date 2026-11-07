"""Shared test setup."""
import unittest
from contextlib import nullcontext
from unittest.mock import patch


def disable_keyboard():
    """Keep unit tests independent of whether stdin is a terminal.

    Use as a module's `setUpModule`. Real key handling is covered by PTY tests.
    """
    patcher = patch('pypomo.cli.keyboard', lambda: nullcontext(None))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)
