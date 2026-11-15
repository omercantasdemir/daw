# DAW (working title)

A guitar-first DAW that runs in the browser, with all audio processing done by a small engine on your own computer.

Built for one workflow: record guitar and bass, program drums on a grid, play with clips (reverse, fades, pan, splits), mix and export. Projects sync to Google Drive so nothing gets lost.

## How it works

```
Browser (web UI)  <-- WebSocket on 127.0.0.1 -->  Local engine (Rust)
 timeline, drum grid,                               audio device, recording,
 mixer, tone panel                                  playback, effects, export,
                                                    project files, Drive sync
```

- **Web UI** (`web/`): Next.js app. It is the screen and the remote control; it never touches audio.
- **Engine** (`engine/`): Rust binary that lives in the system tray. Owns the audio interface, the project on disk and the sync. Audio never passes through the browser, so latency matches a native DAW.

Open the page. If no engine is running, the page offers a download and connects as soon as the engine starts.

## Platforms

| OS | Audio driver |
| --- | --- |
| Windows | ASIO, WASAPI fallback |
| macOS | CoreAudio |
| Linux | PipeWire (JACK API), ALSA fallback |

## Planned features

**v0**
- Audio tracks with live input monitoring
- Drum grid sequencer with a sample kit
- Clip edits: move, split, trim, duplicate, reverse, fades, gain
- Mixer: volume, pan, mute, solo
- Cab IR loader, EQ, reverb
- Export to WAV

**v1**
- Neural Amp Modeler (NAM) loader, noise gate, tone presets
- Pitch/speed, stutter, delay, pan automation
- Google Drive sync with version history
- MP3 export

## Repository layout

```
engine/   Rust audio engine
web/      Browser UI
docs/     Architecture and protocol notes
```

## Status

Early build. The engine is starting as a Python prototype (recorder first); the Rust engine and Next.js UI described above are the earlier design and are under review. Current decisions and open questions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT
