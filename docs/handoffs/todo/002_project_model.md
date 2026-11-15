# 002: Project model (`engine/project.py`) and recording into a project

Model: gemini-3.1-pro
Depends on: 001

## Goal

A project on disk: a folder with `project.json` and an `audio/` folder. The
engine can create, load, validate and save it, do the basic timeline math, and
record a take straight into the armed track as a new clip. No playback yet;
that is task 003, and it will rely on the exact meanings defined here.

## Context (files to read first)

- `README.md`, `docs/ARCHITECTURE.md` (decisions 3, 4, 7, 8, 9, 10, 13)
- `docs/orchestration/BUILDER_RULES.md`
- `engine/audio_io.py`, `cli/record.py`, `tests/conftest.py` (task 001)
- `docs/handoffs/review/001_recorder_core_review.md`

## Requirements

### Schema (`project.json`, format version 1)

```json
{
  "format_version": 1,
  "name": "My song",
  "sample_rate": 44100,
  "tempo_bpm": 120.0,
  "tracks": [
    {
      "id": "t1a2b3c4",
      "name": "Guitar",
      "gain_db": 0.0,
      "pan": 0.0,
      "mute": false,
      "solo": false,
      "armed": false,
      "effects": [],
      "clips": [
        {
          "id": "c9f8e7d6",
          "file": "audio/take_01.wav",
          "start": 0,
          "offset": 0,
          "length": 88200,
          "gain_db": 0.0,
          "pan": 0.0,
          "reverse": false
        }
      ]
    }
  ]
}
```

1. **All positions and lengths are integer frames** at the project sample
   rate. No float seconds are stored. Helpers convert seconds to frames with
   `round(seconds * sample_rate)` and back.
2. Clip fields:
   - `start`: where the clip begins on the timeline.
   - `offset`, `length`: the source region of the file, frames
     `[offset, offset + length)`.
   - `reverse`: the same source region, played backwards. Timeline frame
     `start + i` plays source frame `offset + length - 1 - i`.
   - `gain_db`, `pan`: clip gain in dB, pan from -1.0 (left) to 1.0 (right).
   - `file`: path relative to the project folder, with forward slashes, inside
     `audio/`.
3. `effects` is always an empty list in this task. It exists so the schema
   does not change shape in task 004. Preserve it on load and save.
4. `sample_rate` must be 44100 for now; any other value is a validation error.

### `engine/project.py` (never prints, never prompts)

5. Dataclasses `Project`, `Track`, `Clip`, plus exceptions derived from one
   base class. IDs are short random hex strings, unique within the project.
6. `create_project(folder, name)`: makes the folder, `audio/` and
   `project.json`. Refuses a folder that already contains a `project.json`.
7. `load_project(folder)` and `save_project(project)`:
   - Save is atomic: write a temporary file in the same folder, then
     `os.replace`. A failed save must leave the previous `project.json`
     intact.
   - Output is stable: 2-space indent, fixed key order as in the schema,
     trailing newline. Loading and saving an unchanged project gives a
     byte-identical file.
   - A `format_version` higher than 1 raises a clear error. Unknown extra keys
     are ignored on load.
8. Validation, with an error message that names the track or clip:
   `start >= 0`, `offset >= 0`, `length > 0`, pan within -1..1, gains finite,
   `tempo_bpm > 0`, unique IDs, at most one armed track, `file` relative and
   inside `audio/` (no absolute paths, no `..`). If the audio file exists,
   also: its sample rate is 44100 and `offset + length` does not exceed its
   frame count. A missing audio file is reported by a separate function that
   lists missing files; it does not stop the project from loading.
9. Operations, each returning or mutating plain data, each validated:
   add track, remove track, rename track, arm track (disarms the others),
   add clip, remove clip, move clip (new `start`), set clip gain, pan and
   reverse, trim clip (new `offset` and `length`), and **split clip** at a
   timeline frame.
10. Split rules. Splitting a clip at timeline frame `t` (strictly inside the
    clip) gives two clips that together play exactly what the original
    played. With `k = t - start`:
    - not reversed: left = `(start, offset, k)`, right =
      `(t, offset + k, length - k)`.
    - reversed: left = `(start, offset + length - k, k)`, right =
      `(t, offset, length - k)`; both stay reversed.
    Gain, pan and file are copied; both halves get new IDs.
11. Timeline math helpers: clip end (`start + length`), project length (the
    largest clip end, 0 for an empty project), and the source frame for a
    given timeline frame of a clip (covers reverse).
12. Removing a track or clip never deletes audio files. Recordings are never
    modified (decisions 8 and 10).

### Recording into a project

13. An engine function that records a take into the armed track: the file goes
    to `<project>/audio/` using the existing take naming (prefix = the track
    name made filename-safe, falling back to `take`), through the existing
    `Recorder`. When the take is kept, a clip is added on the armed track with
    `start` = the requested timeline frame, `offset` 0 and `length` = the
    frame count read back from the saved file, and the project is saved.
14. No armed track, or more than one: raise before any stream or file is
    opened.
15. The clip is added only when the take is kept. If the user deletes the
    take, `project.json` is unchanged byte for byte. Redo replaces the take as
    in task 001 and adds one clip at the end.

### CLI (thin)

16. `python -m cli.project new <folder> --name TEXT`, `add-track <folder>
    NAME`, `arm <folder> TRACK` (name or id), `info <folder>` (tracks, clips
    with start and length in seconds and frames, missing files).
17. `python -m cli.record --project <folder> [--at SECONDS]` records into the
    armed track at that timeline position (default 0). Without `--project`
    the recorder behaves exactly as before; the task 001 tests must still
    pass unchanged.

## Out of scope / don't touch

- Playback, mixing, rendering, effects, drum grid, server, web UI.
- Undo history, content-hash file names, tempo maps, time signatures.
- `web/`, `LICENSE`, `README.md`, `docs/ARCHITECTURE.md`, `.gitignore`,
  `AGENTS.md`, `docs/orchestration/`.
- No new dependencies.
- Do not change the behaviour of `engine/audio_io.py`. If a small addition is
  needed there, say so in the status report.

## Done when (run each check and paste the real output)

Automated, `python -m pytest -v` (no hardware; reuse the fake stream):

1. **Round trip.** Build a project with 2 tracks and 3 clips (one reversed),
   save, load: equal objects. Save again: byte-identical file.
2. **Atomic save.** Make the write fail part-way (patch the write or
   `os.replace`); the old `project.json` is intact and loads, and no temporary
   file is left behind.
3. **Validation.** One test per rule in requirement 8, each asserting the
   error names the offending track or clip. Include `../escape.wav`, an
   absolute path, a clip longer than its file, a 48 kHz file, two armed
   tracks, duplicate IDs, and `format_version` 2.
4. **Timeline math.** Clip end, project length (empty and non-empty), and
   seconds-to-frames rounding at values such as 0.1 s and 1/3 s.
5. **Split, sample-exact.** Write a WAV whose samples are a ramp
   (sample value encodes its index). For a normal clip and a reversed clip
   with a non-zero offset, compute the played samples with the
   source-frame helper before the split and after it (left then right):
   identical arrays. Also assert the exact `(start, offset, length)` of both
   halves, and that splitting at the clip's first or last frame boundary is
   rejected.
6. **Record into the armed track.** With the fake stream: the WAV is in
   `audio/`, the clip is on the armed track, `start` equals the requested
   frame, `length` equals the file's frame count, and the project re-loaded
   from disk shows the same.
7. **Delete leaves the project untouched.** `project.json` bytes are equal
   before and after a deleted take. **Redo** ends with exactly one clip.
8. **No armed track** raises, and no file was created in `audio/`.
9. **Removing a clip or track does not delete its audio file.**
10. All task 001 tests still pass, unmodified.

On the real machine:

11. `python -m cli.project new projects/smoke --name Smoke`, `add-track
    projects/smoke Guitar`, `arm projects/smoke Guitar`, then
    `python -m cli.record --project projects/smoke --at 1.5 --seconds 2
    --keep`, then `python -m cli.project info projects/smoke`. Paste the
    outputs and the final `project.json`. The clip's `start` must be 66150.
12. `git status --short`: nothing under `projects/`, `local/` or
    `recordings/`, and no audio files.

## Status report must include: files changed, commands run, check outputs, open questions, skipped items
