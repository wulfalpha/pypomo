# pypomo

A Python CLI timer with named timers and a built-in 25-minute Pomodoro focus timer.
Requires Python 3.12 or newer; no runtime dependencies.

Licensed under the [MIT License](LICENSE).

Install from this directory with `pip install .`, or run with `uv run pypomo`.

```bash
pypomo 15m
pypomo 30s
pypomo 2h
pypomo 1h30m15s
pypomo pomo
pypomo --list
```

Durations use positive whole-number totals with `h`, `m`, and `s`. Compound
units must appear in that order without repeats. Values such as `90m` are valid.
Pre-1.0 versions do not yet support compound durations with spaces:
use `1h30m`, not `1h 30m` (even when quoted).

In a terminal, the countdown updates on one line and rings the terminal bell on
completion. Redirected output contains only the start and completion messages.
Ctrl+C cancels the timer with exit status 130. Invalid input exits with status 2.

## Configuration

Create `~/.config/pypomo/config.json` (or `$XDG_CONFIG_HOME/pypomo/config.json`
when set). Use `--config PATH` to select another file.

```json
{
  "default_units": "minutes",
  "timers": {
    "break": "15m",
    "tea": "4m",
    "pomo": "30m",
    "deep-work": "1h30m"
  }
}
```

With this config, `pypomo 15` means 15 minutes, `pypomo break` means 15 minutes,
and `pypomo pomo` means 30 minutes. Explicit units always take precedence.
`default_units` accepts `seconds`, `minutes`, `hours`, or `s`, `m`, `h`.
Without it, bare numbers are rejected. Configured durations are strings and
use the same syntax and defaults as CLI durations.

Names are case-sensitive, start with a letter, and contain only letters,
digits, underscores, or hyphens. Missing settings retain built-in defaults.
No config is required; an explicitly selected config must exist.
`pomo` currently runs a single focus timer; automatic focus/break cycles are
not implemented yet.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m pypomo 1s
```
