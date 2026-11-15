# 001 recorder core: status

Result: **all "Done when" checks pass** (1–8 automated, 9–11 on the real
Windows 11 machine). See the open questions, especially 1 (which branch this
landed on) and 5 (no real audio interface was connected, so the ASIO smoke take
is digital silence).

## Files changed

| file | what |
|---|---|
| `requirements.txt` | `numpy`, `sounddevice`, `soundfile` |
| `requirements-dev.txt` | `-r requirements.txt` + `pytest` |
| `engine/__init__.py` | package marker |
| `engine/audio_io.py` | devices, preference table, device identity, local config, format check, take naming, take stats, `Recorder` |
| `cli/__init__.py` | package marker |
| `cli/record.py` | `python -m cli.record`: args, device prompts, live meter, Enter/`--seconds`/Ctrl+C stop, stats, keep/redo/delete |
| `tests/conftest.py` | fake input stream + factory (no hardware) |
| `tests/test_audio_io.py` | Done-when checks 1–8 plus a few small extras |
| `tests/test_cli_record.py` | CLI exit codes, end-to-end `--keep` take, delete/redo, unsupported-rate message |
| `docs/handoffs/done/001_recorder_core.md` | task file (moved todo → doing → done) |
| `docs/handoffs/done/001_recorder_core_status.md` | this report |

Not touched: `web/`, `LICENSE`, `README.md`, `docs/ARCHITECTURE.md`,
`.gitignore`, `docs/orchestration/run_log.md`.

### Design notes for the reviewer

- **Plain data across the interface (decision 3).** The CLI never imports
  `sounddevice`. Devices are `InputDevice` dataclasses, the choice is a
  `DeviceChoice`, results are `TakeInfo` / `TakeStats`, warnings are a
  `TakeWarning` enum. Stream open/start failures are wrapped in
  `StreamError(AudioIOError)`.
- **Host API preference** is one table, `HOSTAPI_PREFERENCE`, used by
  `order_devices()` (stable sort; unlisted APIs after).
- **ASIO**: sounddevice 0.5.6 loads its ASIO PortAudio build only if
  `SD_ENABLE_ASIO` is set before the first import (checked in the installed
  `sounddevice.py`). `engine/audio_io.py` imports sounddevice lazily via
  `_sd()`, which does `os.environ.setdefault("SD_ENABLE_ASIO", "1")` on Windows
  first. Check 9 shows ASIO now appears.
- **Format check**: `check_input_settings(device, channels=N, dtype=float32,
  samplerate=44100)`. On failure, and only on `Windows WASAPI`, it retries with
  `WasapiSettings(auto_convert=True)` (documented in the installed version as
  the shared-mode sample-rate converter). If used, `TakeInfo.wasapi_auto_convert`
  is `True` and the CLI prints a note in the stats. Otherwise it raises
  `UnsupportedFormatError` naming the device and its default rate.
- **Channel selection**: the stream is opened with `channels=N` and the
  callback copies column `N-1`.
- **Callback**: checks `status.input_overflow` and records the frame position
  (frames received before this block), copies the column, updates the meter
  peak, and calls `queue.SimpleQueue.put_nowait` (never blocks). No lock, no
  I/O, no printing. The meter reset has a tiny benign race (documented in
  `poll_peak_dbfs`); the file is not affected.
- **Writer thread** drains the queue into `soundfile.SoundFile`. On a write
  error it keeps draining (so memory does not grow) and `stop()` raises the
  error after closing the file.
- **Never overwrite**: `next_take_path()` scans the folder for
  `<prefix>_NN.wav`, next = highest + 1, at least two digits; the folder is
  created. `Recorder.start()` refuses an existing path and then opens the file
  with `open(path, "xb")` (exclusive), handing the file object to `soundfile`.
  The stream is created **before** the file so a device that cannot be opened
  leaves no file behind.
- **`stop()`** is idempotent and always closes stream, writer, `SoundFile` and
  file, then raises the first error, if any. `__exit__` stops and lets the
  original exception (including `KeyboardInterrupt`) propagate.
- **Stats** re-read the file in blocks (`sf.blocks`, float64): peak, RMS,
  clipped samples (`>= CLIP_SAMPLE_LEVEL = 0.999`). Warnings: `CLIPPING` if any
  clipped sample or peak > `CLIP_PEAK_DBFS = -0.1`; `LOW_LEVEL` if peak <
  `LOW_LEVEL_PEAK_DBFS = -30`. `to_dbfs()` uses `math` and returns `-inf` for
  0, so there is no numpy warning.
- **CLI input**: one background `LineReader` thread reads stdin lines into a
  queue. It serves both "Enter to stop" and the prompts, so a line typed for
  one is never swallowed by a leftover `input()`. No `msvcrt`/`select`, so it
  works the same on all three platforms. The main loop uses 0.1 s timeouts, so
  Ctrl+C is handled promptly.
- **Deletion** happens in exactly one place: `cli/record.py` `run()`, after
  the user answers redo or delete. Ctrl+C or end of input at the prompt means
  keep.

## Commands run

```
git status                                   # clean before starting
git mv docs/handoffs/todo/001_recorder_core.md docs/handoffs/doing/001_recorder_core.md
python -m pip install numpy sounddevice soundfile pytest   # sounddevice 0.5.6, soundfile 0.14.0, numpy 2.3.5, pytest 9.2.0 (user site)
python -c "...inspect sounddevice: InputStream, check_input_settings, WasapiSettings, CallbackFlags, SD_ENABLE_ASIO..."
python -m pytest -v
python <scratch>/mutation_check.py           # see check 8
python -m cli.record --list-devices
"18`n1`n" | python -m cli.record --seconds 3 --keep --folder recordings/smoke   # first run, prompts answered via pipe
python -m cli.record --seconds 3 --keep --folder recordings/smoke              # check 10
python -c "<re-read take_02.wav>"
python -m cli.record --device 22 --channel 1 --seconds 2 --keep --folder recordings/smoke --config <scratch>/wasapi_config.json
python -m cli.record --seconds 1 --keep --config <scratch>/gone.json           # expected-error check
git status --short
```

## Check outputs

### 1–8: `python -m pytest -v`

```
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.2.0, pluggy-1.7.0 -- C:\Python314\python.exe
rootdir: C:\Users\omercantasdemir\Desktop\derin öğrenme kodlar\odev\daw
plugins: anyio-4.16.0
collecting ... collected 25 items

tests/test_audio_io.py::test_format_and_sample_accuracy PASSED           [  4%]
tests/test_audio_io.py::test_channel_selection_records_only_the_chosen_channel PASSED [  8%]
tests/test_audio_io.py::test_no_overwrite[None-take] PASSED              [ 12%]
tests/test_audio_io.py::test_no_overwrite[riff-riff] PASSED              [ 16%]
tests/test_audio_io.py::test_next_take_path_continues_after_highest_number PASSED [ 20%]
tests/test_audio_io.py::test_take_name_must_not_be_a_path PASSED         [ 24%]
tests/test_audio_io.py::test_overflows_are_counted_with_frame_positions PASSED [ 28%]
tests/test_audio_io.py::test_full_scale_triggers_clipping PASSED         [ 32%]
tests/test_audio_io.py::test_minus_40_dbfs_triggers_low_level PASSED     [ 36%]
tests/test_audio_io.py::test_minus_12_dbfs_triggers_no_warning PASSED    [ 40%]
tests/test_audio_io.py::test_silence_is_negative_infinity_without_numpy_warnings PASSED [ 44%]
tests/test_audio_io.py::test_meter_poll_returns_peak_since_last_call PASSED [ 48%]
tests/test_audio_io.py::test_exception_mid_recording_leaves_valid_wav PASSED [ 52%]
tests/test_audio_io.py::test_keyboard_interrupt_mid_recording_leaves_valid_wav PASSED [ 56%]
tests/test_audio_io.py::test_config_round_trip PASSED                    [ 60%]
tests/test_audio_io.py::test_resolving_missing_saved_device_raises PASSED [ 64%]
tests/test_audio_io.py::test_device_order_follows_preference_table PASSED [ 68%]
tests/test_audio_io.py::test_callback_does_no_file_io_printing_or_sleeping PASSED [ 72%]
tests/test_cli_record.py::test_no_input_devices_is_one_line_error PASSED [ 76%]
tests/test_cli_record.py::test_missing_saved_device_is_one_line_error PASSED [ 80%]
tests/test_cli_record.py::test_list_devices PASSED                       [ 84%]
tests/test_cli_record.py::test_keep_take_end_to_end PASSED               [ 88%]
tests/test_cli_record.py::test_delete_and_redo[d\n-expected0] PASSED     [ 92%]
tests/test_cli_record.py::test_delete_and_redo[r\n-expected1] PASSED     [ 96%]
tests/test_cli_record.py::test_unsupported_rate_names_device_and_rate PASSED [100%]

============================= 25 passed in 0.52s ==============================
```

Mapping to the Done-when list:

| check | test(s) |
|---|---|
| 1 format + sample accuracy | `test_format_and_sample_accuracy` (1 s 440 Hz sine at 0.5, block sizes 1/37/512/1000/64/4096/333; 44100 Hz, 1 ch, PCM_24, exactly 44100 frames, max error ≤ 2/2**23) |
| 2 channel selection | `test_channel_selection_records_only_the_chosen_channel` (440 Hz on ch1, 1 kHz on ch2; result matches ch2, differs from ch1 and from the mix) |
| 3 no overwrite | `test_no_overwrite[None-take]`, `test_no_overwrite[riff-riff]` (take_01/take_02 and riff_01/riff_02; first file's bytes unchanged; `Recorder` on an existing path raises `FileExistsError`, bytes still unchanged) |
| 4 overflow reporting | `test_overflows_are_counted_with_frame_positions` (flags on blocks 2 and 4 → count 2, frames (300, 700)) |
| 5 stats + warnings | `test_full_scale_triggers_clipping`, `test_minus_40_dbfs_triggers_low_level`, `test_minus_12_dbfs_triggers_no_warning`, `test_silence_is_negative_infinity_without_numpy_warnings` (run under `warnings.simplefilter("error")` and `np.errstate(all="raise")`) |
| 6 interrupted take | `test_exception_mid_recording_leaves_valid_wav` (RuntimeError after 10000 frames → file opens, 10000 frames, samples match), `test_keyboard_interrupt_mid_recording_leaves_valid_wav` |
| 7 config + missing device | `test_config_round_trip` (missing file → None; save/load equal), `test_resolving_missing_saved_device_raises` |
| 8 callback hygiene | `test_callback_does_no_file_io_printing_or_sleeping` (see below) |

**Check 8 detail.** While each fake callback runs, the test patches
`builtins.open`, `os.open`, `builtins.print`, `builtins.input`,
`sys.stdout.write`, `sys.stderr.write` and `time.sleep` to raise. To prove the
test can fail, a scratch script injected `print('x')` and then
`open(__file__).close()` into the callback, ran only that test, and restored
the file:

```
print -> exit 1 ['E       AssertionError: audio callback called print']
open -> exit 1 ['E       AssertionError: audio callback called open']
```

"No blocking calls" is checked by reading the code, not by a test: the only call that could block is the queue put, and it is `SimpleQueue.put_nowait`.

### 9: `python -m cli.record --list-devices`

```
index  host API                    in     rate  name
   18  ASIO                         2    44100  ASIO4ALL v2
   22  Windows WASAPI               2    48000  Mikrofon Dizisi (Dijital Mikrofonlar için Intel® Smart Sound Teknolojisi)
   23  Windows WASAPI               1    44100  İç AUX Girişi (Steam Streaming Speakers)
   24  Windows WASAPI               1    44100  Mikrofon (Steam Streaming Microphone)
   25  Windows WASAPI               2    48000  Stereo Karışımı (Realtek(R) Audio)
    0  MME                          2    44100  Microsoft Ses Eşleştiricisi - Input
    1  MME                          2    44100  Stereo Karışımı (Realtek(R) Aud
    2  MME                          2    44100  Mikrofon Dizisi (Dijital Mikrof
    3  MME                          2    44100  İç AUX Girişi (Steam Streaming 
    4  MME                          2    44100  Mikrofon (Steam Streaming Micro
    9  Windows DirectSound          2    44100  Birincil Ses Yakalama Sürücüsü
   10  Windows DirectSound          2    44100  Stereo Karışımı (Realtek(R) Audio)
   11  Windows DirectSound          2    44100  Mikrofon Dizisi (Dijital Mikrofonlar için Intel® Smart Sound Teknolojisi)
   12  Windows DirectSound          2    44100  İç AUX Girişi (Steam Streaming Speakers)
   13  Windows DirectSound          2    44100  Mikrofon (Steam Streaming Microphone)
exit=0
```

Host APIs: ASIO, Windows WASAPI, MME, Windows DirectSound (WDM-KS is
present but has no devices). **ASIO appears**, with one device, `ASIO4ALL v2`.
No dedicated audio interface is connected. Without `SD_ENABLE_ASIO`, ASIO
does not show up in `query_hostapis()` (checked before writing the code).

### 10: smoke recording

The first run had no saved choice. The prompts were answered through a pipe
(`18`, `1`), and that run created `take_01.wav`. It also exposed a CLI bug:
with stdin at end of input, the meter loop did not wait between refreshes and
printed about 9 MB of meter lines. Fixed (`LineReader.poll` now sleeps for the
interval when input has ended), then check 10 was run as written:

`python -m cli.record --seconds 3 --keep --folder recordings/smoke`

```
Using ASIO4ALL v2 (ASIO), channel 1
Recording to recordings\smoke\take_02.wav  (press Enter to stop, or wait 3 s; Ctrl+C also stops)

[------------------------------]    -inf dBFS  00:00.1      
[------------------------------]    -inf dBFS  00:00.2      
... (one line per 0.1 s; in a terminal these overwrite each other via \r) ...
[------------------------------]    -inf dBFS  00:03.0      
[------------------------------]    -inf dBFS  00:03.1      
Take:      recordings\smoke\take_02.wav
Duration:  3.11 s (137216 frames)
Format:    44100 Hz, 1 ch, PCM_24
Peak:      -inf dBFS
RMS:       -inf dBFS
Clipped:   0 sample(s)
Dropouts:  0
WARNING:   LOW LEVEL: peak below -30 dBFS; raise the input gain.
Kept recordings\smoke\take_02.wav
exit=0
```

Re-read one-liner:

```
python -c "import soundfile as sf, numpy as np; p='recordings/smoke/take_02.wav'; d,sr=sf.read(p); i=sf.info(p); print(p, 'rate', sr, 'channels', i.channels, 'subtype', i.subtype, 'frames', i.frames, 'peak', float(np.max(np.abs(d))))"
recordings/smoke/take_02.wav rate 44100 channels 1 subtype PCM_24 frames 137216 peak 0.0
```

ASIO4ALL delivered digital silence on this laptop (see open question 5). To
confirm that real signal reaches the file, I made one extra take from the
built-in mic over WASAPI. It used a scratch config so the saved choice in
`local/config.json` was not changed. This take also exercised the WASAPI
auto-conversion path (that device's default rate is 48 kHz):

```
Saved device choice to C:\Users\omercantasdemir\.gemini\antigravity\brain\...\scratch\wasapi_config.json
Using Mikrofon Dizisi (Dijital Mikrofonlar için Intel® Smart Sound Teknolojisi) (Windows WASAPI), channel 1 (WASAPI automatic rate conversion)
Recording to recordings\smoke\take_03.wav  (press Enter to stop, or wait 2 s; Ctrl+C also stops)
[------------------------------]  -178.4 dBFS  00:00.1
[------------------------------]  -106.4 dBFS  00:00.3
[#########---------------------]   -42.2 dBFS  00:00.5
[#############-----------------]   -33.2 dBFS  00:00.7
...
[------------------------------]   -60.2 dBFS  00:02.0
Take:      recordings\smoke\take_03.wav
Duration:  2.00 s (88200 frames)
Format:    44100 Hz, 1 ch, PCM_24
Peak:      -33.2 dBFS
RMS:       -55.1 dBFS
Clipped:   0 sample(s)
Dropouts:  0
Note:      recorded with WASAPI automatic sample-rate conversion
WARNING:   LOW LEVEL: peak below -30 dBFS; raise the input gain.
Kept recordings\smoke\take_03.wav
exit=0
```

Expected-error check on the real CLI (saved device that does not exist, scratch config):

```
error: saved device 'Gone Interface' (ASIO) is not available; connect it or choose another device with --device
exit=1
```

The first try of this check found a second bug: a config file with a UTF-8
BOM (PowerShell 5's `Set-Content -Encoding utf8` writes one, and so do some
editors) could not be read. `load_config` now reads with `utf-8-sig`.

### 11: `git status --short` after the checks

```
R  docs/handoffs/todo/001_recorder_core.md -> docs/handoffs/doing/001_recorder_core.md
?? cli/
?? engine/__init__.py
?? engine/audio_io.py
?? requirements-dev.txt
?? requirements.txt
?? tests/conftest.py
?? tests/test_audio_io.py
?? tests/test_cli_record.py
```

No `.wav` files, nothing under `local/` or `recordings/`.

## Open questions

1. **Branch.** `run_log.md` says this run was meant for worktree
   `../daw-wt-001` on branch `task/001-recorder-core`. I was started in the
   main checkout (`daw`, branch `main`), so the work is committed on **`main`**
   (not pushed). The `task/001-recorder-core` branch is unchanged. If the
   commit should live on the task branch, it can be cherry-picked there and
   `main` reset by the reviewer. I did not do that myself.
2. **Linux order.** The task says "ALSA (JACK if present) then the rest". I
   read that as JACK first when present, then ALSA, which matches the README
   ("PipeWire (JACK API), ALSA fallback"). If ALSA should come first, it is
   a one-line change in `HOSTAPI_PREFERENCE`.
3. **ASIO activation.** The engine sets `SD_ENABLE_ASIO=1` (if unset) before
   it imports sounddevice. This only works if nothing imported sounddevice
   before the engine. That is fine for the CLI, but the future server should
   keep importing audio only through `engine/`.
4. **Opening N channels for channel N.** To record channel 8, the stream
   opens 8 input channels. sounddevice also has `AsioSettings(channel_selectors=...)`
   to open just one channel on ASIO. I did not use it, to keep one code path.
   Worth revisiting if a multi-input interface shows CPU or bandwidth issues.
5. **No real interface was connected.** ASIO4ALL produced digital silence on
   this laptop, so the ASIO smoke take (`take_02.wav`) has peak 0.0. The owner
   should repeat check 10 with the guitar/bass interface connected.
6. **Smoke takes left on disk.** `recordings/smoke/take_01.wav`, `take_02.wav`
   (ASIO, silent) and `take_03.wav` (built-in mic, 2 s) exist locally and are
   gitignored. The rules forbid me deleting recordings, so the owner can
   delete them. `local/config.json` now holds `ASIO4ALL v2 / ASIO / channel 1`
   from the first run. `--device` on the next run changes it.
7. **`--seconds` precision.** The CLI stops at the first meter tick after the
   limit, so a take runs up to about 0.1 s plus one block longer (3.11 s for
   `--seconds 3`). Trimming to the exact length was not asked for.
8. **Dependencies installed.** `sounddevice` and `pytest` were not installed
   and I installed them into the user site of Python 3.14 (`pip install`, no
   venv). Only 3.14 was available to test; the code uses no syntax newer than
   3.11.

## Skipped items

- **Interactive terminal checks were not done by hand.** I had no interactive
  terminal, so these were not tried by a person: pressing Enter to stop,
  Ctrl+C during a real take, and the first-run prompts typed at a keyboard.
  The prompts were exercised through a pipe. Enter-to-stop and delete/redo
  were exercised through stdin in tests. The engine side of Ctrl+C is covered
  by `test_keyboard_interrupt_mid_recording_leaves_valid_wav`. The CLI's
  `except KeyboardInterrupt` path is covered only by reading the code. Please
  try `python -m cli.record`, press Ctrl+C mid-take, and confirm the stats
  show and the take is kept.
- macOS and Linux were not run (Windows-only machine). The code uses
  `pathlib`, has no Windows-only modules, and only touches the ASIO env var
  when `sys.platform == "win32"`.
- Nothing else from the task was skipped.
