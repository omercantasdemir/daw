# 001 recorder core: review

Verdict: **pass.** Reviewed commit `02632f9` on 2026-11-15. One thing is still
unproven and only the owner can prove it: a take from the real audio interface
(see "Owner test").

## What was checked

| check | result |
|---|---|
| `python -m pytest -q`, re-run by the reviewer | 25 passed |
| Smoke takes re-read from disk by the reviewer | all three are 44100 Hz, 1 channel, PCM_24; `take_03` (built-in mic) has real signal, peak 0.022 |
| Files in the commit | only task files; nothing under `web/`, no `LICENSE`, `README.md`, `ARCHITECTURE.md`, `.gitignore` or orchestration files touched |
| Audio or local config committed | none |
| Attribution in commit message or files | none; author and committer are the owner |
| Platform-specific modules (`msvcrt`, `termios`, `select`, `ctypes`) | none |

## Code review against the risk list

- **Audio format.** The stream is opened at 44100 Hz float32 and the file is
  written as mono `PCM_24`. The sample-accuracy test compares every sample of
  a known sine against the file within 2 LSB of 24-bit, with uneven block
  sizes, so a dropped, duplicated or reordered block would fail it.
- **No silent resampling.** `check_format` raises with the device name and
  its rate. The one exception, WASAPI automatic conversion, is recorded in
  `TakeInfo.wasapi_auto_convert` and printed by the CLI, as the task allowed.
- **Channel selection.** The callback copies column `channel - 1`. The test
  uses two different signals and also rules out a mix of both.
- **Callback.** It only checks the overflow flag, copies one column, updates
  the peak and calls `SimpleQueue.put_nowait`. No file I/O, printing, locks or
  sleeping. The hygiene test patches `open`, `print`, `sleep` and stdout, and
  the builder showed the test fails when a `print` or `open` is injected.
- **Dropouts.** Overflows are counted with frame positions and shown in the
  stats and the live meter. Not ignored.
- **Never overwrite.** `open(path, "xb")` (exclusive create) plus an explicit
  existence check; the test compares the first file's bytes before and after.
- **Interrupted takes.** `stop()` is idempotent, closes stream, writer and
  file in every path, and the tests re-open the file after a `RuntimeError`
  and after a `KeyboardInterrupt`.
- **Deletion.** One place only (`cli/record.py`, after the user answers redo
  or delete). End of input or Ctrl+C at the prompt means keep.
- **Engine is UI-agnostic.** `engine/audio_io.py` has no `print` or `input`.
  The CLI does not import `sounddevice`; it only sees dataclasses and enums.
- **Stats.** Computed by re-reading the file, as required. dBFS uses `math`
  and returns negative infinity for silence.

## Accepted as built (builder's open questions)

- **Linux order is JACK, then ALSA.** Matches the README. Accepted.
- **`--seconds` overshoots by about 0.1 s** (3.11 s for `--seconds 3`). The
  task did not ask for exact trimming. Accepted for now; exact lengths belong
  to the project model in task 002.
- **Recording channel N opens N channels.** Fine for a 2-input interface.
  Revisit only if a large multi-input interface shows a problem.
- **Meter reset race.** The meter can miss one block's peak. The file and the
  take stats are unaffected. Accepted.
- **Work landed on `main`** instead of a task branch. The owner started the
  run in the main checkout, so this is expected.

## Notes carried forward

1. **ASIO needs the engine to import `sounddevice` first.** The engine sets
   `SD_ENABLE_ASIO=1` before its lazy import. Anything that imports
   `sounddevice` earlier loses ASIO. Now recorded as a decision in
   `docs/ARCHITECTURE.md`; the server task (006) must respect it.
2. **Packages were installed into the user's Python, not a virtual
   environment.** The builder rules did not forbid it. A rule has been added
   for future tasks.
3. **The Ctrl+C path in the CLI was verified only by reading the code.** The
   engine side is tested. Covered by the owner test below.
4. **The queue between callback and writer is unbounded.** If the disk stalls
   for a long time, memory grows. Acceptable for a recorder; note for the
   long-session work later.
5. The status report contained one path into the builder's private scratch
   folder; the reviewer replaced it with `<scratch>`.

## Owner test (needed before task 002 relies on this)

The only real device on the machine during the build was ASIO4ALL with nothing
connected, which gave digital silence. With the guitar interface connected:

```
python -m cli.record --list-devices
python -m cli.record --device <index of your interface> --channel <input number>
```

Play, press Enter to stop, and check: the meter moves while you play, the
stats show a sensible peak (roughly -18 to -6 dBFS for DI), dropouts are 0,
and the file in `recordings/` sounds right. Then start another take and press
Ctrl+C in the middle: stats should still appear and the take should be kept.

Leftovers from the build that the owner may delete: `recordings/smoke/`
(three short takes, two of them silent). `local/config.json` currently points
at ASIO4ALL; the `--device` run above replaces it.
