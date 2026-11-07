# Changelog

All notable changes to pypomo are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/wulfalpha/pypomo/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/wulfalpha/pypomo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wulfalpha/pypomo/releases/tag/v0.1.0
