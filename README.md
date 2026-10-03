# pypomo

A Python CLI timer with named timers and configurable Pomodoro routines.
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

In a terminal, the timer name and `HH:MM:SS` countdown update on a single line:
`pomo · 00:24:59 remaining`. Completion or cancellation replaces that line,
then ends it with a newline so your shell prompt starts cleanly. Completion
also rings the terminal bell.

Redirected output contains separate start and completion (or cancellation)
lines without terminal control characters. Use `--live` to force in-place
updates through a pipe, for example `pypomo 5m --live | lolcat`. The receiving
program must support terminal control sequences and flush output promptly.
Ctrl+C cancels the timer with exit status 130. Invalid input exits with status 2.

## Configuration

Create `~/.config/pypomo/config.toml` (or `$XDG_CONFIG_HOME/pypomo/config.toml`
when set). TOML supports comments and sections:

```toml
default_units = "minutes"

[timers]
break = "15m"
lunch = "30m"
deep-work = "1h30m"

[pretty]
enabled = false # Use --pretty to enable for a single run

[pretty.bar]
enabled = true
width = 20
filled = "█"
empty = "░"

[pretty.colors]
enabled = true
label = "cyan"
remaining = "white"
bar = "green"
complete = "green"
cancelled = "yellow"
```

Existing `config.json` files remain supported with the same settings as nested
JSON objects. If both files exist, `config.toml` takes precedence; files are not
merged. Use `--config PATH` to explicitly select a `.toml` or `.json` file.
An invalid TOML config reports an error rather than silently falling back to JSON.

With this config, `pypomo 15` means 15 minutes, `pypomo break` means 15 minutes,
and `pypomo pomo` runs the default Pomodoro routine. Explicit units always take precedence.
`default_units` accepts `seconds`, `minutes`, `hours`, or `s`, `m`, `h`.
Without it, bare numbers are rejected. Configured durations are strings and
use the same syntax and defaults as CLI durations.

Names are case-sensitive, start with a letter, and contain only letters,
digits, underscores, or hyphens. Missing settings retain built-in defaults.
No config is required; an explicitly selected config must exist.
`pomo` is reserved for the default Pomodoro routine. For a single focus timer,
use `pypomo 25m` or define a timer named `focus`.

## Pomodoro routines

`pypomo pomo` runs four 25-minute focus sessions, with 5-minute short breaks
between them and a 15-minute long break after the last focus session. Phases
advance automatically; the routine finishes after the long break rather than
repeating indefinitely. Ctrl+C cancels the entire routine.

Customize the default or add named routines in your config:

```toml
[pomo]
focus = "25m"
short_break = "5m"
long_break = "15m"
rounds = 4

[pomodoros.sprint]
focus = "15m"
short_break = "3m"
long_break = "10m"
rounds = 3
```

```bash
pypomo pomo --pretty
pypomo sprint.pomo --pretty
pypomo --list
```

`rounds` is a positive integer counting focus sessions. A one-round routine
has one focus session followed by a long break, with no short break.
Durations must be positive strings, using the same duration syntax and
`default_units` as ordinary timers. Omitted default settings use built-in
values; custom routines inherit omitted settings from the configured `[pomo]`.
Routine names follow the same naming rules as timers. A timer `sprint` and a
routine `sprint.pomo` can coexist.

The display includes the routine name, phase and round, such as
`sprint.pomo · focus 1/3`. Live output stays on one line across phase changes;
the progress bar measures the current phase and resets at each transition.
The terminal bell rings when each phase ends. Redirected output records the
start and completion of each phase on separate lines.

For compatibility, a legacy `[timers] pomo = "25m"` setting (or its JSON
equivalent) supplies the default routine's focus duration. An explicit
`[pomo] focus` takes precedence. **The `pomo` command now runs a complete
routine, even with a legacy config**, rather than a single focus timer.
JSON supports the same structure using `pomo` and `pomodoros` objects.

## Pretty output

```bash
pypomo pomo --pretty
pypomo pomo --no-pretty
pypomo 5m --pretty --live
```

`--pretty` enables the configured bar and theme; `--no-pretty` overrides
`pretty.enabled = true`. Without a flag, the config decides (default: false).
The progress bar fills as time elapses and remains visible on completion or
cancellation. Disable `pretty.bar.enabled` for colors only, or disable
`pretty.colors.enabled` for a bar without colors. Disable both to retain plain
text. Each styled segment resets its color so it does not affect the shell prompt.

Bar width is 1–80 characters. Filled and empty glyphs must each be a single
narrow printable character (for example `#` and `-`, or `█` and `░`); spaces
are allowed, but emoji, wide characters, combining marks and control characters
are rejected. Choose a width that fits your terminal. Available colors are
`black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`, and `default`
(the terminal's default foreground). Actual shades follow your terminal palette.

Styling applies to terminal output or output forced live with `--live`.
Redirected output remains plain without `--live`, even with `--pretty`.
For coloring with an external program, use `pypomo 5m --live | lolcat`;
add `--no-pretty` if styling is enabled in your config.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m pypomo 1s
```
