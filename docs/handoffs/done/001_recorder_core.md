# 001: Recorder core (`engine/audio_io.py` + `cli/record.py`)

Model: gemini-3.1-pro
Depends on: none

## Goal

A command-line recorder the owner can use today to record guitar or bass DI
from an audio interface: pick the device and input channel once, watch a live
peak meter, record a mono 44.1 kHz 24-bit WAV, see the take's stats, then keep,
redo or delete it. The recording logic lives in `engine/` and is reused later
by the project model and the server.

## Context (files to read first)

- `README.md`
- `docs/ARCHITECTURE.md` (decisions 3, 4, 5, 9, 10 apply directly)
- `docs/orchestration/BUILDER_RULES.md`
- `.gitignore` (`local/`, `recordings/` and `*.wav` are ignored)
- sounddevice documentation for: `query_devices`, `query_hostapis`,
  `InputStream`, `CallbackFlags`, `check_input_settings`, `WasapiSettings`, and
  how ASIO is enabled on Windows. Check the docs for the installed version; do
  not rely on memory.

There is no existing Python code in the repo. `engine/README.md` and
`web/README.md` are placeholders; leave `web/` alone.

## Requirements

### Setup

1. Add `requirements.txt` (`numpy`, `sounddevice`, `soundfile`) and
   `requirements-dev.txt` (`pytest`). No other dependencies.
2. Add `engine/__init__.py`, `cli/__init__.py`, `tests/`. The CLI runs as
   `python -m cli.record` from the repo root. Code must work on Python 3.11+.

### `engine/audio_io.py` (never prints, never prompts)

3. **Device listing.** A function that returns the input devices as
   dataclasses: index, name, host API name, max input channels, default sample
   rate. A second function returns them ordered by host API preference:
   Windows ASIO then WASAPI then the rest; macOS CoreAudio; Linux ALSA (JACK if
   present) then the rest. The preference order is a small table, not scattered
   `if` statements.
4. **Device identity.** A saved device is identified by name + host API name,
   not by index, because indices change between sessions. Resolving a saved
   choice that no longer exists raises a clear exception.
5. **Local config.** Load/save of the chosen device, host API and input channel
   in `local/config.json` (path overridable). Missing file means "no choice
   yet", not an error.
6. **Format check.** Before opening the stream, verify the device accepts
   44100 Hz on the chosen channel. If not, raise an exception that names the
   device and the rate it does support. Do not silently record at another rate.
   On WASAPI, automatic rate conversion may be used if the sounddevice docs
   support it; if it is used, the take info must say so.
7. **`Recorder` class.** Opens an input stream, takes exactly one input channel
   (1-based channel number in the public interface), and writes mono WAV,
   44100 Hz, subtype `PCM_24`.
   - The audio callback only: copies the block, puts it on a queue, updates the
     running peak, and counts overflow flags. No file I/O, no printing, no
     blocking calls.
   - A writer thread drains the queue into a `soundfile.SoundFile`.
   - `start()`, `stop()` and a context manager. `stop()` always leaves a valid,
     closed WAV file, including when called after an exception or Ctrl+C.
   - A method the UI layer polls for the meter: peak since the last call, in
     dBFS.
   - Overflows (input dropouts) are counted, with the frame position of each
     one, and returned in the take info. They are never ignored.
   - The stream is created through an injectable factory so tests can feed a
     known signal without audio hardware.
8. **Never overwrite.** The output file is created in exclusive mode. Naming:
   `take_NN.wav` in the chosen folder, NN = next free number, at least two
   digits. With a name: `<name>_NN.wav`. The number is chosen by scanning the
   folder, and the folder is created if missing.
9. **Take stats**, computed by re-reading the saved file from disk: duration in
   seconds, frame count, sample rate, channels, subtype, peak dBFS, RMS dBFS,
   number of clipped samples (absolute value at or above 0.999), overflow
   count. Warnings as data, not text printed by the engine: clipping (any
   clipped sample or peak above -0.1 dBFS) and low level (peak below
   -30 dBFS). Thresholds are named constants.
10. dBFS of digital silence must not crash or print a numpy warning; return
    negative infinity.

### `cli/record.py` (thin: argument parsing, printing, prompting only)

11. Arguments: `--list-devices`, `--device` (index or name substring),
    `--channel N`, `--folder PATH` (default `recordings/`), `--name TEXT`,
    `--seconds N`, `--keep` (skip the keep/redo/delete prompt and keep),
    `--config PATH`.
12. First run with no saved choice: show the ordered device list, ask for
    device and channel, save the choice. Later runs reuse it and print which
    device and channel are in use. `--device` / `--channel` override and
    update the saved choice.
13. While recording: one-line live peak meter, refreshed about 10 times per
    second, with a visible clip indicator. Stop with Enter, or automatically
    after `--seconds`. Waiting for Enter must work on all three platforms (no
    `msvcrt`-only code).
14. Ctrl+C during a take stops cleanly: the file is closed and valid, stats are
    shown, and the take is kept unless the user chooses otherwise.
15. After the take: print the stats and any warnings, then ask
    keep / redo / delete. Redo deletes this take and records again under the
    same file name. Delete removes only this take. These are the only places
    any file is deleted.
16. Exit code 0 on success, non-zero with a one-line message on errors (no
    input devices, saved device missing, unsupported rate). No tracebacks for
    expected errors.

## Out of scope / don't touch

- `web/`, `LICENSE`, `README.md`, `docs/ARCHITECTURE.md`, `.gitignore`.
- No playback, monitoring, effects, project files, stereo, other sample rates,
  server or GUI.
- No `pedalboard` in this task.
- No denoiser-specific folders or file naming.

## Done when (run each check and paste the real output)

Automated, with `python -m pytest -v` (tests use the injected fake stream, no
hardware):

1. **Format and sample accuracy.** Feed a known 1 s, 440 Hz sine at amplitude
   0.5 in uneven block sizes. Re-read the WAV from disk and assert: sample rate
   44100, channels 1, subtype `PCM_24`, exactly 44100 frames, and every sample
   within 2 / 2**23 of the source.
2. **Channel selection.** Fake device with 2 channels carrying different
   signals; recording channel 2 yields the second signal, not the first and not
   a mix.
3. **No overwrite.** Two takes in the same folder produce `take_01.wav` and
   `take_02.wav`; the first file's bytes are unchanged. Opening an existing
   path raises instead of overwriting. Same for `--name`.
4. **Overflow reporting.** Fake stream raises the overflow flag on two blocks;
   take info reports count 2 and their frame positions.
5. **Stats and warnings.** Full-scale signal triggers the clipping warning;
   a -40 dBFS signal triggers the low-level warning; a -12 dBFS signal triggers
   neither; silence gives negative infinity without warnings from numpy.
6. **Interrupted take.** An exception raised mid-recording still leaves a WAV
   that `soundfile` can open, with the frames written so far.
7. **Config round trip and missing device.** Save, load, get the same choice;
   resolving a saved device that is not in the device list raises the clear
   exception.
8. **Callback hygiene.** A test that fails if the callback opens a file or
   writes to stdout (for example by patching `open`/`print` during the fake
   callback), or state plainly how this was verified instead.

On the real machine (Windows 11):

9. `python -m cli.record --list-devices` and paste the output. State which
   host APIs appear and whether ASIO does.
10. If an input device exists: `python -m cli.record --seconds 3 --keep
    --folder recordings/smoke`, then a one-liner that re-reads the file and
    prints sample rate, channels, subtype, frames, peak. Paste both outputs.
    If no input device exists, say so and skip.
11. `git status --short` after the checks: no `.wav` and nothing under
    `local/` or `recordings/` is listed.

## Status report must include: files changed, commands run, check outputs, open questions, skipped items
