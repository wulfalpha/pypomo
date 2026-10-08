# pypomo: review and improvements

*Review of commit `d725adc` (2026-10-03).*

> **Where the tests live:** the edge-case tests behind this review are in
> [`tests/test_edge_cases.py`](tests/test_edge_cases.py) and run with the normal suite
> (`PYTHONPATH=src python -m unittest discover -s tests -v`). Each test for a known bug below
> is named `test_bug_*` and marked `@unittest.expectedFailure`, so CI stays green. When you fix
> a bug, its test reports an *unexpected success*, which fails the run. **Remove the
> `expectedFailure` marker as each bug is fixed.** The real-pseudo-terminal tests (`PtyEdges`)
> are skipped on non-Linux platforms, and the signal/pipe tests (`ProcessEdges`) are skipped on
> non-POSIX platforms.

## Summary

pypomo is a small command-line countdown timer for Python 3.12 or newer, with no runtime dependencies. You can give it durations (`25m`, `1h30m15s`), named timers from a TOML or JSON config, and finite Pomodoro routines (`pypomo pomo`, `pypomo sprint.pomo`). Output is either a single line that updates in place (on a TTY, or with `--live`) or plain start/end lines when piped. There's also an optional progress bar and colors (`--pretty`). The project is in good shape for 0.1.0. The code is compact (about 360 lines across 7 modules), it uses a monotonic clock, it validates config strictly with clear messages, its exit codes are documented (2 for bad input, 130 for Ctrl-C), and the README matches what the code does. All 28 existing tests pass on Python 3.13.5 (venv) and 3.12.15 (installed wheel built with `uv build`). They also pass on 3.11, even though `requires-python` says 3.12+. Most of what I found is about how the timer behaves at its edges: output pipes that close early, signals other than SIGINT, terminals that aren't UTF-8, extreme inputs, and the countdown display drifting slowly over time. The core parsing and config logic held up well.

## Bugs found (most severe first)

Every bug below was reproduced. The matching expected-failure test in `tests/test_edge_cases.py` is named in brackets.

### 1. Traceback on a broken pipe (`pypomo 25m | head -1`, `--live | lolcat` when the reader exits)
[`test_bug_broken_pipe_no_traceback`]
- **Reproduce:** `pypomo 2s | head -1`, or `pypomo 3s --live | head -c 10`
- **Observed:** a full `BrokenPipeError` traceback plus `Exception ignored on flushing sys.stdout`, with exit status 120.
- **Expected:** a quiet exit, as other Unix tools do. The README encourages piping (`--live | lolcat`), and this happens whenever the downstream program exits first, for example when you quit `lolcat`/`less` or a script reads only the first line.
- **Where:** `src/pypomo/timer.py:27` (`print(..., flush=True)`). Nothing in `cli.py:58-66` handles it.
- **Fix:** in `cli.main`, catch `BrokenPipeError`. Then point stdout at devnull so the flush at interpreter shutdown doesn't raise again, and return 141 (or 0):
  ```python
  except BrokenPipeError:
      devnull = os.open(os.devnull, os.O_WRONLY)
      os.dup2(devnull, sys.stdout.fileno())
      return 141  # 128 + SIGPIPE
  ```

### 2. Crash when stdout can't encode `·` / `█` (ASCII locales, Windows code pages, some CI runners)
[`test_bug_non_utf8_stdout`]
- **Reproduce:** `PYTHONIOENCODING=ascii pypomo 1s` crashes before it prints anything. `PYTHONIOENCODING=cp1252 pypomo 1s --live --pretty` crashes on the bar glyphs. (With `LANG=C` alone it works, because Python 3.7+ coerces the C locale to UTF-8.)
- **Observed:** `UnicodeEncodeError` traceback, exit 1.
- **Expected:** the timer runs. At worst it falls back to ASCII separators and glyphs.
- **Where:** the separator `' · '` is hard-coded at `timer.py:25` and `pretty.py:88`, and the default glyphs are at `pretty.py:16-17`. The write happens at `timer.py:27`.
- **Why it matters:** on Windows, redirected output (`pypomo 25m > log.txt`) uses the ANSI code page. cp1252 can encode `·`, but most other code pages (cp437, cp932, cp936…) can't. With `--live --pretty` the default `█░` fails under cp1252 too.
- **Fix:** call `sys.stdout.reconfigure(errors='replace')` once at startup. Better still, check `sys.stdout.encoding` and switch to `' - '` and `#`/`-` when the characters can't be encoded (`'·'.encode(enc)` inside a try).

### 3. SIGTERM / SIGHUP kill the timer silently and leave a half-drawn line
[`test_bug_sigterm_reports_cancellation`]
- **Reproduce:** run `pypomo 10s > log &`, then `kill -TERM %1` (or `kill -HUP`). Also happens with `timeout 5 pypomo 10s`, closing the terminal tab, or `tmux kill-pane`.
- **Observed:** exit 143 or 129. The log contains only `10s · 00:00:10 remaining`, with no `cancelled at …` line. On a TTY, the in-place line is left without a newline, so the shell prompt gets glued onto it.
- **Expected:** the same cleanup as Ctrl-C (a cancellation line, then a newline), followed by exit 128+signum.
- **Where:** `cli.py:65` only handles `KeyboardInterrupt`, and no signal handlers are installed.
- **Fix:** at startup, map SIGTERM (and SIGHUP where it exists) to a custom exception, or simply raise `KeyboardInterrupt`:
  ```python
  def _terminate(signum, frame): raise KeyboardInterrupt
  for name in ('SIGTERM', 'SIGHUP'):
      if hasattr(signal, name): signal.signal(getattr(signal, name), _terminate)
  ```
  To keep the exit code accurate, give the custom exception a `signum` and return `128 + signum`.

### 4. The countdown sometimes skips a second (`00:01:05 → 00:01:03`)
[`test_bug_no_skipped_seconds_with_realistic_oversleep`]
- **Reproduce:** use a fake clock where each `sleep(x)` takes `x + ε`, which is what really happens. I measured ε at about 0.14–0.27 ms per tick on this Linux box. Over a 25-minute timer, ε = 2 ms skips 2 displayed seconds and ε = 15 ms (typical Windows timer granularity) skips 22.
- **Observed:** some values are never drawn. The deadline itself stays correct, because it uses the monotonic clock, so this is cosmetic.
- **Expected:** every second is shown.
- **Where:** `timer.py:37` sleeps a fixed `min(1, remaining)`. The oversleep piles up until `ceil(remaining)` drops by 2 in a single tick. On Linux this happens about once every 1–2 hours of timing. On Windows it's roughly once a minute.
- **Fix:** sleep until just past the next whole-second boundary instead of a fixed second:
  ```python
  time.sleep(min(remaining, remaining - math.ceil(remaining) + 1 + 0.005))
  ```
  Also, drop the duplicate first frame: `timer.py:30` draws the full duration, and then the loop draws the same value again right away (visible in `--live` output).

### 5. Extremely large durations: traceback, or a timer that can never tick
[`test_bug_huge_duration_clean_error`, `test_bug_huge_duration_precision`]
- **Reproduce:** `pypomo 1000…0s` with 400 zeros raises `OverflowError: int too large to convert to float` (traceback, exit 1). `pypomo 100000000000000000000h` starts, but at that size float spacing is about 10⁸ s, so the display can never change.
- **Expected:** a usage error with exit 2, for example "Duration too long (max 99h / 1 week)". Separately, 4301+ digit input already gets exit 2, but with Python's confusing `Exceeds the limit (4300 digits)…` message.
- **Where:** `durations.py:26-30` has no upper bound, and `timer.py:18` (`time.monotonic() + seconds`) overflows.
- **Fix:** add a `MAX_SECONDS` (for example `7 * 86400` or `100 * 3600`) check in `parse_duration`. Reject amounts with more than about 9 digits before calling `int()` so the error message stays clean.

### 6. Crash when stdout is closed (`pypomo 25m >&-`, some daemon/launcher contexts)
[`test_bug_closed_stdout_no_traceback`]
- **Observed:** `AttributeError: 'NoneType' object has no attribute 'isatty'` at `timer.py:17`.
- **Expected:** run silently (and still exit 0 at the deadline) or report a clean error.
- **Fix:** `interactive = live or (sys.stdout is not None and sys.stdout.isatty())`, and skip `print` when `sys.stdout is None`. Low impact, but trivial to fix.

### 7. Config files with a UTF-8 BOM are rejected
[`test_bug_utf8_bom_accepted`]
- **Reproduce:** save `config.json` or `config.toml` with a BOM (older Windows Notepad and PowerShell 5 `Out-File -Encoding utf8` do this).
- **Observed:** `Cannot read config …: Unexpected UTF-8 BOM` for JSON, or `Invalid statement (at line 1, column 1)` for TOML. The TOML message is especially confusing.
- **Fix:** `config.py:32`, `path.read_text(encoding='utf-8-sig')`. This is a one-word change and is harmless for files without a BOM.

### 8. A relative `XDG_CONFIG_HOME` is used instead of being ignored
[`test_bug_relative_xdg_config_home_ignored`]
- **Observed:** with `XDG_CONFIG_HOME=relative/dir`, the config path resolves relative to the current directory, so a different config gets loaded depending on where you run `pypomo`.
- **Expected:** the XDG Base Directory spec says relative values must be ignored, so it should fall back to `~/.config`.
- **Where / fix:** `config.py:23`. Use `xdg = os.environ.get('XDG_CONFIG_HOME'); base = Path(xdg) if xdg and os.path.isabs(xdg) else Path.home() / '.config'`.

### Possible issues (reasoned, not reproduced here)
- **Possible: laptop sleep pauses the timer (Linux and macOS).** `time.monotonic()` is `CLOCK_MONOTONIC` on Linux and `mach_absolute_time` on macOS, and neither advances while the system is suspended. If you start a 25-minute focus session, close the lid for 10 minutes, and reopen it, the timer still shows the time it had before suspend, so you'll end up working about 35 wall-clock minutes. Pomodoro users usually expect wall-clock behavior. I couldn't suspend the container to confirm. Fix: on Linux use `time.clock_gettime(time.CLOCK_BOOTTIME)` when available. On macOS, `CLOCK_MONOTONIC_RAW` doesn't count sleep either, so you could compare against `time.time()` and handle large forward jumps. Otherwise, document the behavior.
- **Possible: garbled output in legacy Windows consoles.** `\r\033[2K` and the SGR colors need VT processing. Windows Terminal turns it on by default, but classic `conhost`/`cmd.exe` doesn't, and Python doesn't enable it for you. CI only covers Linux and macOS. Fix: on Windows, call `os.system('')` once or use `SetConsoleMode` via ctypes, and add `windows-latest` to the CI matrix.
- **Possible: double Ctrl-C prints a traceback.** A second SIGINT that arrives while the cancellation line is being printed (`timer.py:39-42`) escapes as an unhandled `KeyboardInterrupt` from inside `except`. The window is very small, so I didn't reproduce it reliably.

## Edge cases tested that passed
- **Durations:** I tried 20 malformed inputs: `0s`, `0h0m0s`, `000m`, `-1s`, `+5m`, `1.5m`, `1e3s`, uppercase units, missing number or unit, repeated or out-of-order units, Arabic-Indic and full-width digits, trailing newline, tab, NBSP, and empty. All were rejected with exit 2 and a clear message. Boundary-valid values all parsed correctly: `1s`, `0h0m1s`, `007m`, `1h60m`, `100h`. `default_units` works with bare numbers, and `0`/bad units are rejected.
- **CLI:** no arguments, `--list` together with a timer, `-5m` (treated as an unknown option, exit 2), unknown flags, extra positional arguments, `''`, `.pomo`, `pomo.pomo`, ambiguous `--l`, and `--pretty=yes` all exit 2 without starting a timer. Abbreviations (`--liv`, `--pret`) work, and the last of `--pretty`/`--no-pretty` wins. Timer names like `h` or `m5` can't collide with duration syntax. `--help` works, and `--version` matches the package metadata.
- **Config:** these all raise a clean `ValueError`, which becomes exit 2 from the CLI: truncated TOML or JSON, empty JSON, JSON `[]` or `null`, invalid UTF-8, wrong value types (including a TOML datetime and JSON `NaN` for rounds), `.yaml` suffix, permission denied (chmod 000), a directory sitting at `config.toml`, a missing explicit `--config`, and a corrupt default config. An empty TOML file gives the defaults. `default_units` applies no matter where the key appears. The legacy `timers.pomo` works alongside a routine named `pomo`. Glyph validation rejects soft hyphen, zero-width space, emoji, two-character strings, and tab, and accepts space, `#`, `█`, and `é`.
- **Timer logic (mocked clock):** non-TTY output is exactly two plain lines even with `--pretty`. The timer finishes exactly at the deadline. With ideal sleeps, every second is shown. Changing the wall clock (`time.time`) has no effect. A forward jump of the monotonic clock finishes cleanly with no negative sleep. The bar is always exactly the configured width, even when `remaining` is out of range. Cancelling during a short break stops the whole routine. A one-round routine is focus followed by the long break.
- **Real processes:** a real 1 s timer works. SIGINT gives exit 130 with a cancellation line. Five instances running at once don't interfere (there's no shared state file). While suspended with SIGSTOP, time keeps counting and the timer finishes right after SIGCONT (as designed: there's no pause feature). `--list` works with stdin closed and `XDG_CONFIG_HOME` empty.
- **Real PTY:** the display stays on one line with `\r\033[2K` and ends with a bell and a newline. Ctrl-C (`\x03`) in the PTY gives exit 130 with `cancelled at 00:00:0…`. With `--pretty`, a routine stays on one line across phase changes.
- **Packaging:** `uv build` produces a correct sdist and wheel, the entry point works, and the existing suite passes against the installed wheel on 3.12.

## Code quality and structure
- **Version string is hard-coded** at `cli.py:22` and has to stay in sync with `pyproject.toml` by hand. Use `importlib.metadata.version('pypomo')`, with a fallback when running from source.
- **`run_timer` mixes timing, rendering, and I/O** (`timer.py:15-43`). Splitting it into a pure `ticks(deadline, clock)` generator and a `Display` object (TTY, plain, or pretty) would make bugs 1, 2, 4, and 6 easier to fix and test, and would give an obvious place to add pause/resume later.
- **`parse_pretty` packs three validation tables into one loop** (`pretty.py:46-71`) with `name == 'pretty'` special cases, and gives one generic error message for every failure. Per-field validators with specific messages would be clearer (for example "pretty.bar.width must be 1–80, got 0").
- **The name regex is duplicated** at `config.py:60` and `:75`. Move it into one `NAME_RE` constant. The duration regex is also duplicated, in `cli.py:25-26` and `durations.py:19`.
- **`default_config_path()` runs while argparse is being built** (`cli.py:17`), so every invocation hits the filesystem. Harmless, but it's an odd dependency for `--version`.
- **`main()` mutates the loaded config** (`config.pretty.enabled = args.pretty`, `cli.py:60`). Fine for a CLI, but `dataclasses.replace` would keep `load_config` results immutable for tests.
- **`Pomodoro.rounds` has no upper bound.** `rounds = 99999999999999999999` is accepted (tomllib is more lenient than the TOML spec's 64-bit limit). A sanity cap such as ≤ 100 would catch typos.
- Add type checking (`mypy --strict` passes easily on code this small) and `ruff` to CI.

## Testing gaps (specific tests to add)
1. Broken pipe in plain and `--live` mode: subprocess piped into `head -c 10`, assert no `Traceback` (bug 1).
2. Run with `PYTHONIOENCODING=ascii` and `cp1252`, plain and `--live --pretty`, and assert exit 0 (bug 2).
3. SIGTERM and SIGHUP in a subprocess: assert a `cancelled at` line and exit 143/129 (bug 3).
4. A fake clock with `sleep(x)` advancing `x + 0.015` over 1500 s: assert every second appears (bug 4).
5. Bounds checks: `parse_duration('1' + '0'*400 + 's')` and `'100000000000000000000h'` must raise `ValueError` (bug 5).
6. `sys.stdout = None` (or `>&-`) (bug 6). A BOM-prefixed config (bug 7). A relative `XDG_CONFIG_HOME` (bug 8).
7. **A real PTY test** (`pty.fork`), which the original suite didn't have. The README says "terminal appearance still needs manual testing", but `tests/test_edge_cases.py` now has a working PTY harness (`PtyEdges.run_pty`, Linux only for now) that checks single-line output, the bell, and Ctrl-C in a real terminal. It takes about 2 s per test.
8. **Real-signal SIGINT test.** The original Ctrl-C tests all patch `time.sleep` to raise. A subprocess and `send_signal(SIGINT)` test catches problems with signal-handler installation.
9. Add Windows to CI (`windows-latest`) to cover encoding, ANSI, and path behavior. Optionally add 3.13/3.14, and 3.11 if `requires-python` is lowered.
10. Property-based tests for `parse_duration` (Hypothesis): `parse_duration(format(h,m,s)) == h*3600+m*60+s`, and the order rule.

## Packaging, docs, and UX
- **`requires-python = ">=3.12"` is stricter than it needs to be.** The full suite passes on 3.11.17 (tomllib was added in 3.11). Lower it to `>=3.11`, or note the reason for 3.12.
- **Respect `NO_COLOR` and `TERM=dumb`.** Right now `NO_COLOR=1 TERM=dumb pypomo 1s --live --pretty` still sends SGR colors and `\033[2K`. See https://no-color.org.
- **Pause/resume/skip aren't supported.** Ctrl-Z doesn't pause (stopped time still counts), and the only way to skip a phase is to cancel the whole routine. Worth adding if this is meant for daily Pomodoro use: for example, keyboard controls on a TTY (`p` pause, `s` skip phase, `q` quit) using `termios`/`select`, or SIGTSTP/SIGCONT handling that pauses the deadline. Document the current behavior in the meantime.
- **Optional desktop notification or sound hooks**, for example `on_complete = "notify-send pypomo done"` in the config. The terminal bell alone is easy to miss when the terminal isn't focused. Keep it optional so there are still no runtime dependencies.
- **README:** mention the 141/143 exit codes once bugs 1 and 3 are fixed. Document laptop-suspend behavior (see Possible issues). On Windows, the config path is `%USERPROFILE%\.config\pypomo`, which is unusual. Consider `%APPDATA%\pypomo`, or at least document it.
- **Better error for `pypomo -5m`.** Right now you get "unrecognized arguments: -5m". A specific "durations must be positive" message would be friendlier. Since `parse_known_args` is already used, look for a leading `-` followed by a digit in `extras`.
- `pyproject.toml` lacks `[project.urls]` (Homepage, Issues) and `classifiers`. Add them before publishing to PyPI.
- Consider publishing with `uv publish` or trusted publishing from CI, and add a `CHANGELOG.md`.

## Prioritized next steps
1. Handle `BrokenPipeError` and closed stdout (bugs 1 and 6). That's a few lines in `cli.py`/`timer.py`.
2. Make output encoding-safe with ASCII fallbacks (bug 2), and add Windows to CI.
3. Treat SIGTERM/SIGHUP like Ctrl-C (bug 3).
4. Sleep to the second boundary and drop the duplicate first frame (bug 4).
5. Add a maximum duration (bug 5), `utf-8-sig` (bug 7), and the absolute-path check for XDG (bug 8).
6. Remove each `expectedFailure` marker in `tests/test_edge_cases.py` as its bug is fixed, and check the PTY tests on macOS so they can run there too.
7. Decide on laptop-suspend behavior (BOOTTIME vs. documenting it), then consider pause/skip controls and `NO_COLOR`.
