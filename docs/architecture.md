# Architecture

The full, living design doc is kept separately. This file holds the stable summary.

## Components

- **Web UI**: Next.js + TypeScript, Zustand state, canvas timeline. Mirrors project state and sends every change to the engine as a command.
- **Local engine**: Rust. Threads: real-time audio (no allocation, no locks), disk streaming, control (WebSocket), sync (Google Drive).
- **Link**: WebSocket on `127.0.0.1`, origin-checked, paired with a one-time code.

## Engine modules

| Module | Job |
| --- | --- |
| `device` | Enumerate interfaces, open streams, latency settings |
| `transport` | Play, stop, loop, punch-in, metronome, tempo |
| `graph` | Tracks, clips, buses, effect chains, mixer |
| `record` | Input capture, monitoring, take files |
| `drums` | Grid sequencer and sample player |
| `fx` | Gain, pan, EQ, reverb, delay, gate, cab IR, NAM |
| `render` | Offline bounce to WAV/MP3 |
| `project` | JSON load/save, media store, undo history |
| `sync` | Google Drive (`drive.file` scope) |
| `server` | WebSocket API, pairing, auth |

## Principles

- Clip edits are non-destructive: recordings are never modified; clips hold settings (reverse, fades, gain, offsets).
- The engine is the source of truth; undo lives there.
- Recordings are immutable and named by content hash, so each uploads to Drive once.
