import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypomo.cli import main
from pypomo.config import Config, default_config_path, load_config
from pypomo.pretty import Pretty, parse_pretty, render
from pypomo.timer import run_timer


class PrettyTests(unittest.TestCase):
    def test_validation(self):
        for data in (None, {'enabled': 1}, {'bar': []}, {'typo': True},
                     {'colors': {'label': 'orange'}}, {'bar': {'width': True}},
                     {'bar': {'width': 0}}, {'bar': {'width': 81}},
                     *({'bar': {'filled': char}} for char in ('', 'ab', '\n', '\033', '界', '\u0301'))):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_pretty(data)

    def test_progress_and_custom_glyphs(self):
        pretty = parse_pretty({'enabled': True, 'bar': {'width': 4, 'filled': '#', 'empty': '-'},
                               'colors': {'enabled': False}})
        for remaining, expected in ((10, '[----]'), (5, '[##--]'), (0, '[####]')):
            self.assertEqual(render('tea', 'status', remaining, 10, pretty), f'tea · {expected} · status')

    def test_colors_without_bar(self):
        pretty = parse_pretty({'bar': {'enabled': False}, 'colors': {'label': 'red'}})
        text = render('tea', 'complete', 0, 10, pretty, 'complete')
        self.assertEqual(text, '\033[31mtea\033[0m · \033[32mcomplete\033[0m')

    def test_cli_overrides(self):
        for configured, flag, expected in ((False, '--pretty', True), (True, '--no-pretty', False),
                                            (True, None, True), (False, None, False)):
            config = Config(pretty=Pretty(enabled=configured))
            with patch('pypomo.cli.load_config', return_value=config), patch('pypomo.cli.run_timer') as timer:
                main(['1s'] + ([flag] if flag else []))
                self.assertEqual(timer.call_args.kwargs['pretty'].enabled, expected)

    def test_output_modes(self):
        for live in (False, True):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), \
                 patch('pypomo.timer.time.monotonic', side_effect=[0, 0, 1]), \
                 patch('pypomo.timer.time.sleep'):
                run_timer(1, 'tea', live=live, pretty=Pretty(enabled=True))
            text = output.getvalue()
            if live:
                self.assertIn('░' * 20, text)
                self.assertIn('█' * 20, text)
                self.assertIn('\033[32mcomplete\033[0m', text)
                self.assertEqual(text.count('\n'), 1)
            else:
                self.assertEqual(text, 'tea · 00:00:01 remaining\ntea · complete\n')

    def test_styled_cancellation(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
             patch('pypomo.timer.time.monotonic', side_effect=[0, 0, 5]), \
             patch('pypomo.timer.time.sleep', side_effect=KeyboardInterrupt), \
             self.assertRaises(KeyboardInterrupt):
            run_timer(10, 'tea', live=True, pretty=Pretty(enabled=True))
        self.assertIn('█' * 10 + '░' * 10, output.getvalue())
        self.assertIn('\033[33mcancelled at 00:00:05 remaining\033[0m\n', output.getvalue())

    def test_toml_and_discovery(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            folder = Path(directory) / 'pypomo'
            folder.mkdir()
            toml = folder / 'config.toml'
            legacy = folder / 'config.json'
            self.assertEqual(default_config_path(), toml)
            legacy.write_text('{"timers": {"tea": "4m"}}')
            self.assertEqual(default_config_path(), legacy)
            toml.write_text('default_units = "minutes"\n[timers]\ntea = "3"\n[pretty]\nenabled = true\n'
                            '[pretty.bar]\nfilled = "#"\n[pretty.colors]\nenabled = false\n')
            self.assertEqual(default_config_path(), toml)
            config = load_config(toml)
            self.assertEqual(config.timers['tea'], 180)
            self.assertTrue(config.pretty.enabled)
            self.assertEqual(config.pretty.bar.filled, '#')
            self.assertFalse(config.pretty.colors.enabled)
            self.assertEqual(load_config(legacy).timers['tea'], 240)
            toml.write_text('[invalid')
            with self.assertRaisesRegex(ValueError, 'Cannot read config'):
                load_config(default_config_path())
