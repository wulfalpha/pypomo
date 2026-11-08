# Changelog

All notable changes to pypomo are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-11-07

Live countdown data for JSON lines readers.

### Added
- Each release tag also creates a GitHub release with the changelog notes and
  the built files. Releases 0.1.0 through 0.3.1 were added retroactively.
- `--ticks` adds a `tick` record each second to `--format jsonl` output, for
  status bars and other live displays. Ticks are not written while paused and
  never run hooks.
- JSON records have an `ends_at` field: when the countdown will reach zero on
  `start`, `resume`, and `tick` records, and `null` otherwise.

## [0.3.1] - 2026-11-07

First release on PyPI, as `pypomodo`. No changes to timer behavior.

### Added
- Tag-triggered publishing to PyPI with trusted publishing.

### Changed
- The distribution is named `pypomodo` for PyPI. The `pypomo` command, the
  `pypomo` Python package, and the `~/.config/pypomo` config location are
  unchanged. If you installed from git with uv or pipx, uninstall the old
  `pypomo` tool before reinstalling (`uv tool uninstall pypomo`).
- The build backend requirement is now `uv_build>=0.13.7,<0.14.0`, so building
  with current uv no longer warns or fetches an older backend.

## [0.3.0] - 2026-11-07

### Added
- Ctrl+Break on Windows cancels the timer like SIGTERM, with a cancellation line.
- `--format jsonl` writes one JSON object per event to stdout instead of the
  countdown display, with the same fields as hook variables plus `time`.
- A `wait` event, for hooks and JSON output, when a routine waits for Enter
  before a phase; quitting while waiting sends `cancel`.
- Package keywords, classifiers, and project URLs; a `dev` dependency group
  for `uv sync`.

### Changed
- CI tests Python 3.12 through 3.15.
- Tests are grouped by module, and the CLI entry point is split into smaller functions.

## [0.2.0] - 2026-11-07

### Added
- Pause and resume a running timer with `p` or Space; `q` cancels like Ctrl+C.
  Keys work whenever stdin is the foreground terminal, including with
  redirected output, which records `paused at …` and `resumed at …` lines.
- `auto_start` routine setting and `--auto-start` / `--no-auto-start` flags.
  When disabled, each phase after the first waits for Enter.
- Event hooks: a `[hooks]` table maps `start`, `end`, `pause`, `resume`,
  `cancel`, or `any` to a command, with `PYPOMO_*` environment variables.
  `--hook CMD` adds a one-off hook; `--no-hooks` ignores configured hooks.
  Hooks run in the background and never affect the timer.
- `pretty.colors.paused` for paused and ready-to-start lines.
- `d` (days) duration unit, such as `2d` or `1d 12h`, and `days` for `default_units`.
- `--preview` ends with an estimated end time: `Ends: 14:35 if started now`.

### Changed
- Spaced compound durations such as `1h 30m` (quoted or not, and in config
  files) are accepted. Previously they were rejected with an error.

## [0.1.0] - 2026-10-08

First version: a terminal countdown timer with named timers and finite
Pomodoro routines, no runtime dependencies, Python 3.12+.

### Added
- Durations such as `25m` and `1h30m15s`, with optional `default_units`
  for bare numbers; durations are limited to 365 days.
- Named timers and Pomodoro routines (`pomo`, `NAME.pomo`) from a TOML or
  legacy JSON config in the XDG config directory, or `--config PATH`.
- Single-line live countdown on a terminal (or with `--live`), plain
  start/end lines when redirected, and the terminal bell on completion.
- `--pretty` progress bar and colors, configurable under `[pretty]`, adapting
  to terminal width.
- `--list`, `--preview`, `--silent`, and `--version`.
- Documented exit statuses: 2 for invalid input, 130 for Ctrl+C, 143 and 129
  for SIGTERM and SIGHUP, and 141 for a closed output pipe.
- CI on Linux, macOS, and Windows with lint, build, installed-wheel tests,
  and Linux pseudo-terminal tests.

### Fixed
Hardening from the [October 2026 review](docs/review-2026-10.md):
- Quiet exit on broken pipes, including Windows closed-pipe errors.
- Encoding-safe output with ASCII fallbacks for non-UTF-8 streams.
- SIGTERM and SIGHUP cancel cleanly with a cancellation line.
- The countdown no longer skips seconds from accumulated sleep overshoot.
- Very large durations, closed stdout, UTF-8 BOM configs, and relative
  `XDG_CONFIG_HOME` values are handled.
- `NO_COLOR` and `TERM=dumb` are respected.

[Unreleased]: https://github.com/wulfalpha/pypomo/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/wulfalpha/pypomo/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/wulfalpha/pypomo/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/wulfalpha/pypomo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/wulfalpha/pypomo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wulfalpha/pypomo/releases/tag/v0.1.0
