# Architecture

Status: **working baseline** (2026-11-15). The owner's goal is the most useful
approach in practice, with latency as a concern but not yet measured. So the
plan is: build the useful parts first in Python, measure latency on the real
interface, and move only the real-time path to native code if the numbers
require it (decision 12).

## What this is

A guitar-first DAW to replace Mixcraft 8 Home Studio for one workflow: record
guitar and bass DI, run amp sims and effects, program drums on a step grid,
edit clips (gain, pan, reverse, cut), mix and export. It must run on Windows,
Linux and macOS.

## Two parts

```
Browser (web UI)  <-- HTTP + WebSocket on 127.0.0.1 -->  Local engine
 timeline, drum grid,                                     audio device, recording,
 mixer, effect panels                                     playback, effects, render,
                                                          project files, (later) sync
```

- **Web UI** (`web/`): the screen and the remote control. It never touches
  audio.
- **Local engine** (`engine/`): a program on the user's PC that owns the audio
  interface and the project on disk. Audio never passes through the browser.
- **CLI** (`cli/`): thin command-line tools over the engine. First deliverable,
  and useful for testing every engine feature before the UI exists.

## Decisions

1. **The engine is Python for now.** Libraries: `sounddevice` (device I/O),
   `soundfile` (WAV), `numpy`, and Spotify `pedalboard` (effects, VST3 hosting,
   offline rendering). All four have builds for Python 3.14 (checked
   2026-11-15).
2. **Known limit of Python.** Garbage collection and the GIL can cause stutters
   in real-time paths. That is acceptable for recording to disk, offline
   rendering and prototype monitoring. If live latency becomes a problem, the
   real-time path moves to native code (Rust or JUCE/C++).
3. **The audio core sits behind a clean interface** so it can be swapped for
   native code later without changing the CLI, the server or the UI. Callers
   use plain data (dataclasses, numbers, paths), never library objects such as
   a `sounddevice` stream.
4. **Core audio classes never print and never prompt.** They return values or
   raise exceptions. The CLI and the web UI are thin layers on top.
5. **Audio callbacks do no slow work**: no file I/O, no printing, no waiting on
   locks. A callback hands blocks to a queue; a separate thread writes to disk.
6. **Engine ↔ UI**: the engine runs a local server (FastAPI + WebSocket on
   `127.0.0.1`) with project, transport and record commands. Details are
   decided in the task that builds it (006), not up front.
7. **Project format**: a folder with `project.json` (tracks, clips, positions,
   effect parameters, tempo) and an `audio/` folder of WAV files.
   Human-readable and easy to sync.
8. **Clip edits are non-destructive.** Recordings are never modified. A clip
   holds settings (start, offset, length, gain, pan, reverse) that point into a
   recording.
9. **Recording format**: mono, 44.1 kHz, WAV PCM 24-bit.
10. **Recordings are never overwritten** and never deleted without the user
    explicitly choosing it.
11. **License**: `pedalboard` is GPLv3, so anything distributed with it must be
    under GPLv3 terms. See open question 1.
12. **Latency is decided by measurement, not up front.** Recording to disk,
    editing, offline render and playback do not need low latency and stay in
    Python. The one latency-critical feature is hearing an amp sim live while
    playing. Task 004 includes a round-trip latency measurement of live
    monitoring through `pedalboard` on the owner's interface. Rule of thumb:
    about 10 ms or less round trip feels fine, above about 20 ms is
    distracting. If Python cannot reach that, the real-time path (input →
    effects → output) is rebuilt as a small native core behind the same
    interface, and everything else stays as it is. Until then, the owner
    monitors through the interface's direct monitoring or an existing
    standalone amp sim while recording the DI.

## Folder layout

```
engine/          audio_io.py (devices, Recorder); later: project model, mixer,
                 renderer, effects, server
cli/             record.py (thin CLI over the engine)
web/             browser UI (later)
tests/           pytest
docs/            ARCHITECTURE.md, orchestration/, handoffs/
```

## Roadmap

| task | what |
|---|---|
| 001 recorder core | device selection, mono 24-bit recording, meter, take stats |
| 002 project model | `project.json` schema, load/save, recording into a track |
| 003 playback and render | offline mixdown, then play/stop/seek |
| 004 effects | per-track `pedalboard` chain, VST3 amp sim by path |
| 005 drum grid | step grid rendered from one-shot samples, tempo-synced |
| 006 engine server | FastAPI + WebSocket API over the engine |
| 007 web UI MVP | timeline, clips, transport, record button, meters |
| 008 Drive sync | optional Google Drive project sync (later) |

Mixcraft stays in use until 002 and 003 are reliable.

## Earlier design (commit `123a54d`) and what changed

The first version of this file described a Rust engine and a Next.js UI. The
engine/UI split, the localhost WebSocket link, non-destructive clips and the
JSON project format are unchanged. What changed: the engine starts in Python
instead of Rust, and the effects come from `pedalboard` instead of being
written by hand. These ideas from the earlier design are **not decided** and
are parked until the task that needs them: tray app, pairing code and origin
check for the WebSocket, recordings named by content hash, undo history in the
engine, Neural Amp Modeler and cab IR loading, MP3 export, Zustand and a canvas
timeline in the UI.

## Open questions for the owner

1. **License.** The repo is MIT. MIT code may use a GPLv3 library, but any
   build that is distributed with `pedalboard` falls under GPLv3. Simplest
   honest option: relicense the repo to GPL-3.0-or-later. Alternative: keep MIT
   for the source and state that distributed engine builds are GPLv3. Must be
   settled before task 004 (first use of `pedalboard`).
2. **Web UI stack**: decided in task 007. Next.js + TypeScript from the earlier
   design is the default candidate.
3. **Stereo and other sample rates**: mono 44.1 kHz only for now. Revisit if
   the owner's interface or a plugin needs 48 kHz.

Settled on 2026-11-15: the repo's home is `omercantasdemir/daw`; the native
engine question is answered by decision 12.
