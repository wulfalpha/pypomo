"""Print GitHub release notes for a version from CHANGELOG.md.

Usage: python scripts/release_notes.py v0.4.0 [CHANGELOG.md]

Prints the version's section without its heading, with relative links made
absolute, followed by install instructions. Exits with an error if the
changelog has no section for the version.
"""
import re
import sys

REPO = 'https://github.com/wulfalpha/pypomo/blob/main/'
INSTALL = 'Install from PyPI: `uv tool install pypomodo` or `pipx install pypomodo` (the command is `pypomo`).'


def release_notes(version: str, changelog: str) -> str:
    version = version.removeprefix('v')
    match = re.search(rf'^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)',
                      changelog, re.M | re.S)
    if not match or not match.group(1).strip():
        raise ValueError(f'CHANGELOG.md has no section for {version}')
    body = re.sub(r'\]\((?!https?://|#|mailto:)([^)]+)\)', rf']({REPO}\1)', match.group(1).strip())
    return f'{body}\n\n{INSTALL}\n'


if __name__ == '__main__':
    path = sys.argv[2] if len(sys.argv) > 2 else 'CHANGELOG.md'
    with open(path, encoding='utf-8') as file:
        text = file.read()
    try:
        sys.stdout.write(release_notes(sys.argv[1], text))
    except ValueError as exc:
        sys.exit(f'error: {exc}')
