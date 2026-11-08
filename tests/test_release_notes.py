"""scripts/release_notes.py, used by the Publish workflow."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_notes', ROOT / 'scripts' / 'release_notes.py')
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## [Unreleased]

## [1.1.0] - 2026-12-01

### Added
- See the [guide](docs/guide.md), the [site](https://example.com), and [below](#notes).

## [1.0.0] - 2026-11-01

First release.

[Unreleased]: https://example.com/compare
[1.1.0]: https://example.com/1.1.0
"""


class ReleaseNotesTests(unittest.TestCase):
    def test_section_between_headings_with_absolute_links(self):
        notes = release_notes.release_notes('v1.1.0', CHANGELOG)
        self.assertTrue(notes.startswith('### Added\n- See the [guide]('
                                         'https://github.com/wulfalpha/pypomo/blob/main/docs/guide.md)'))
        self.assertIn('[site](https://example.com)', notes)
        self.assertIn('[below](#notes)', notes)
        self.assertNotIn('1.0.0', notes)
        self.assertTrue(notes.endswith(release_notes.INSTALL + '\n'))

    def test_last_section_stops_at_link_references(self):
        notes = release_notes.release_notes('1.0.0', CHANGELOG)
        self.assertEqual(notes, f'First release.\n\n{release_notes.INSTALL}\n')

    def test_missing_or_empty_section_is_an_error(self):
        for version in ('v2.0.0', 'Unreleased', 'v1.1'):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'no section'):
                release_notes.release_notes(version, CHANGELOG)

    def test_every_tagged_release_has_notes_in_the_real_changelog(self):
        text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        for version in ('0.1.0', '0.2.0', '0.3.0', '0.3.1'):
            with self.subTest(version=version):
                self.assertIn('###', release_notes.release_notes(version, text))


if __name__ == '__main__':
    unittest.main()
