"""Configuration loading and validation."""
import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import POSIX, disable_keyboard, run_cli

from pypomo.config import Config, default_config_path, load_config
from pypomo.pretty import parse_pretty

setUpModule = disable_keyboard


class ConfigTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            return load_config(path)

    def test_overrides(self):
        config = self.load({'default_units': 'minutes', 'timers': {'break': '15', 'pomo': '1h30m'}})
        self.assertEqual(config.timers, {'break': 900})
        self.assertEqual(config.pomo.focus, 5400)
        self.assertEqual(self.load({}).pomo.focus, 1500)

    def test_invalid_config(self):
        for data in ([], {'default_units': []}, {'default_units': None},
                     {'timers': []}, {'timers': {'15m': '2m'}},
                     {'timers': {'tea': 4}}, {'timers': {'tea': '0m'}}, {'typo': 1}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.load(data)

    def test_missing_and_malformed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            self.assertEqual(load_config(path).pomo.focus, 1500)
            with self.assertRaises(ValueError):
                load_config(path, required=True)
            path.write_text('{', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Cannot read config'):
                load_config(path)


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


if __name__ == '__main__':
    unittest.main()
