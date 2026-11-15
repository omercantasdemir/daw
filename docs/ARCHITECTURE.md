# Architecture

Status: **draft, waiting for the owner's OK** (2026-11-15). Task 001 does not
depend on the open questions at the bottom. Task 002 does not start before the
OK.

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
2. **Is Rust still the long-term engine?** The README says "Local engine
   (Rust)". Proposed wording: Python prototype now, native real-time core later
   only if latency requires it.
3. **Which GitHub repo is the home**: `online-daw-project` (has the first
   commit) or `daw` (empty)?
4. **Web UI stack**: keep Next.js + TypeScript from the earlier design, or
   decide in task 007?
5. **Stereo and other sample rates**: mono 44.1 kHz only for now. Is 48 kHz
   needed for your interface?
