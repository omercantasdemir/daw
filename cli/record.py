"""Record mono 44.1 kHz 24-bit takes from an audio interface.

Run from the repo root::

    python -m cli.record --list-devices
    python -m cli.record                      # first run asks for device + channel
    python -m cli.record --seconds 30 --name riff

This module only parses arguments, prints and prompts. All audio work is done
by :mod:`engine.audio_io`.
"""

from __future__ import annotations

import argparse
import math
import queue
import sys
import threading
import time
from pathlib import Path

from engine import audio_io as aio

METER_INTERVAL_SECONDS = 0.1
METER_WIDTH = 30
METER_FLOOR_DBFS = -60.0
DEFAULT_FOLDER = Path("recordings")

WARNING_TEXT = {
    aio.TakeWarning.CLIPPING: "CLIPPING: the take hit full scale; lower the input gain.",
    aio.TakeWarning.LOW_LEVEL: (
        f"LOW LEVEL: peak below {aio.LOW_LEVEL_PEAK_DBFS:g} dBFS; raise the input gain."
    ),
}


class UsageError(Exception):
    """An expected CLI error shown as one line."""


class LineReader:
    """Reads stdin lines on a background thread so the main loop never blocks.

    One reader serves both "press Enter to stop" and the prompts, so a line
    typed for one is never swallowed by a leftover ``input()`` call. Works the
    same on Windows, Linux and macOS (no ``msvcrt``/``select`` on stdin).
    """

    _EOF = object()

    def __init__(self) -> None:
        self._lines: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._eof = False

    def _read_loop(self) -> None:
        while True:
            line = sys.stdin.readline()
            if not line:
                self._lines.put(self._EOF)
                return
            self._lines.put(line.rstrip("\r\n"))

    def _ensure_thread(self) -> None:
        # On a terminal, an empty read can be spurious (e.g. after Ctrl+C on
        # Windows), so a new reader is started for the next request.
        if self._eof and not sys.stdin.isatty():
            return
        if self._thread is None or not self._thread.is_alive():
            self._eof = False
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()

    def clear(self) -> None:
        """Drop lines typed before now (e.g. extra Enters before a take)."""
        while True:
            try:
                item = self._lines.get_nowait()
            except queue.Empty:
                return
            if item is self._EOF:
                self._eof = True

    def poll(self, timeout: float) -> str | None:
        """Return a line if one arrives within ``timeout`` seconds, else None.

        End of input also returns None (recording then stops only by
        ``--seconds`` or Ctrl+C).
        """
        self._ensure_thread()
        if self._eof and not sys.stdin.isatty():
            time.sleep(timeout)  # no more input; still pace the caller's loop
            return None
        try:
            item = self._lines.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is self._EOF:
            self._eof = True
            return None
        return item

    def prompt(self, text: str) -> str | None:
        """Print ``text`` and wait for a line. Returns None at end of input."""
        print(text, end="", flush=True)
        self._ensure_thread()
        while True:
            if self._eof and not sys.stdin.isatty():
                print()
                return None
            try:
                # Short timeout so Ctrl+C is handled promptly on every platform.
                item = self._lines.get(timeout=METER_INTERVAL_SECONDS)
            except queue.Empty:
                continue
            if item is self._EOF:
                self._eof = True
                print()
                return None
            return item.strip()


# --- Formatting ----------------------------------------------------------------------


def format_db(value: float) -> str:
    """Format a dBFS value; silence shows as -inf."""
    return "-inf" if value == -math.inf else f"{value:.1f}"


def print_devices(devices: list[aio.InputDevice]) -> None:
    """Print the input devices, best host API first."""
    print(f"{'index':>5}  {'host API':<26} {'in':>3}  {'rate':>7}  name")
    for d in devices:
        print(
            f"{d.index:>5}  {d.hostapi:<26} {d.max_input_channels:>3}  "
            f"{d.default_samplerate:>7g}  {d.name}"
        )


def meter_line(peak_dbfs: float, clipped: bool, seconds: float, overflows: int) -> str:
    """One-line peak meter, e.g. ``[######----]  -12.3 dBFS  00:04.2  CLIP``."""
    if peak_dbfs == -math.inf:
        filled = 0
    else:
        fraction = (peak_dbfs - METER_FLOOR_DBFS) / -METER_FLOOR_DBFS
        filled = round(max(0.0, min(1.0, fraction)) * METER_WIDTH)
    bar = "#" * filled + "-" * (METER_WIDTH - filled)
    minutes, secs = divmod(seconds, 60)
    parts = [f"[{bar}]", f"{format_db(peak_dbfs):>6} dBFS", f"{int(minutes):02d}:{secs:04.1f}"]
    if overflows:
        parts.append(f"dropouts: {overflows}")
    parts.append("CLIP" if clipped else "    ")
    return "  ".join(parts)


def print_stats(stats: aio.TakeStats, info: aio.TakeInfo) -> None:
    """Print take stats and warnings."""
    print(f"Take:      {stats.path}")
    print(f"Duration:  {stats.duration_seconds:.2f} s ({stats.frames} frames)")
    print(f"Format:    {stats.samplerate} Hz, {stats.channels} ch, {stats.subtype}")
    print(f"Peak:      {format_db(stats.peak_dbfs)} dBFS")
    print(f"RMS:       {format_db(stats.rms_dbfs)} dBFS")
    print(f"Clipped:   {stats.clipped_samples} sample(s)")
    print(f"Dropouts:  {stats.overflow_count}", end="")
    if info.overflow_frames:
        shown = ", ".join(str(f) for f in info.overflow_frames[:10])
        more = " ..." if len(info.overflow_frames) > 10 else ""
        print(f" (at frame {shown}{more})", end="")
    print()
    if info.wasapi_auto_convert:
        print("Note:      recorded with WASAPI automatic sample-rate conversion")
    for warning in stats.warnings:
        print(f"WARNING:   {WARNING_TEXT[warning]}")


# --- Device choice ---------------------------------------------------------------------


def prompt_int(reader: LineReader, text: str, valid) -> int:
    """Ask until the answer is an int accepted by ``valid``."""
    while True:
        answer = reader.prompt(text)
        if answer is None:
            raise UsageError("no answer on input; use --device and --channel")
        if answer.isdigit() and valid(int(answer)):
            return int(answer)
        print("Not a valid choice.")


def choose_device(
    args: argparse.Namespace, devices: list[aio.InputDevice], reader: LineReader
) -> tuple[aio.InputDevice, int]:
    """Work out device and channel from arguments, saved config or prompts.

    The choice is saved when it differs from the saved one.
    """
    saved = aio.load_config(args.config)
    if args.device is not None:
        device = aio.select_device(args.device, devices)
    elif saved is not None:
        device = aio.resolve_device(saved, devices)
    else:
        print("No saved input device. Available input devices (best first):")
        print_devices(devices)
        indices = {d.index for d in devices}
        index = prompt_int(reader, "Device index: ", lambda i: i in indices)
        device = aio.select_device(str(index), devices)

    same_device = (
        saved is not None
        and saved.device_name == device.name
        and saved.hostapi == device.hostapi
    )
    if args.channel is not None:
        channel = args.channel
    elif same_device:
        channel = saved.channel
    elif device.max_input_channels == 1:
        channel = 1
    else:
        channel = prompt_int(
            reader,
            f"Input channel (1-{device.max_input_channels}): ",
            lambda c: 1 <= c <= device.max_input_channels,
        )
    aio.validate_channel(device, channel)

    choice = aio.DeviceChoice(device.name, device.hostapi, channel)
    if choice != saved:
        aio.save_config(choice, args.config)
        print(f"Saved device choice to {args.config}")
    return device, channel


# --- Recording -------------------------------------------------------------------------


def record_take(
    path: Path,
    device: aio.InputDevice,
    channel: int,
    wasapi_auto_convert: bool,
    seconds: float | None,
    reader: LineReader,
) -> tuple[aio.TakeInfo, bool]:
    """Record one take with a live meter. Returns (take info, interrupted)."""
    reader.clear()
    limit = f", or wait {seconds:g} s" if seconds else ""
    print(f"Recording to {path}  (press Enter to stop{limit}; Ctrl+C also stops)")
    recorder = aio.Recorder(path, channel, device, wasapi_auto_convert=wasapi_auto_convert)
    clipped = False
    interrupted = False
    recorder.start()
    try:
        while True:
            if seconds and recorder.elapsed_seconds >= seconds:
                break
            if reader.poll(METER_INTERVAL_SECONDS) is not None:
                break
            peak = recorder.poll_peak_dbfs()
            clipped = clipped or peak > aio.CLIP_PEAK_DBFS
            line = meter_line(peak, clipped, recorder.elapsed_seconds, recorder.overflow_count)
            print("\r" + line, end="", flush=True)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        info = recorder.stop()
    print()
    if interrupted:
        print("Stopped by Ctrl+C; the file is closed and kept.")
    return info, interrupted


def ask_keep_redo_delete(reader: LineReader) -> str:
    """Ask what to do with the take. End of input or Ctrl+C means keep."""
    while True:
        try:
            answer = reader.prompt("[k]eep, [r]edo or [d]elete this take? [k]: ")
        except KeyboardInterrupt:
            print()
            return "keep"
        if answer is None or answer.lower() in ("", "k", "keep"):
            return "keep"
        if answer.lower() in ("r", "redo"):
            return "redo"
        if answer.lower() in ("d", "delete"):
            return "delete"
        print("Please answer k, r or d.")


def run(args: argparse.Namespace) -> int:
    """Run the recorder CLI. Returns the exit code."""
    devices = aio.list_input_devices_ordered()
    if not devices:
        raise aio.NoInputDevicesError("no input devices found")
    if args.list_devices:
        print_devices(devices)
        return 0

    reader = LineReader()
    device, channel = choose_device(args, devices, reader)
    wasapi_auto_convert = aio.check_format(device, channel)
    note = " (WASAPI automatic rate conversion)" if wasapi_auto_convert else ""
    print(f"Using {device.name} ({device.hostapi}), channel {channel}{note}")

    path = aio.next_take_path(args.folder, args.name)
    while True:
        info, _ = record_take(path, device, channel, wasapi_auto_convert, args.seconds, reader)
        print_stats(aio.analyze_take(info.path, info.overflow_count), info)
        choice = "keep" if args.keep else ask_keep_redo_delete(reader)
        if choice == "keep":
            print(f"Kept {path}")
            return 0
        # The only places a file is deleted: the user chose redo or delete.
        path.unlink()
        if choice == "delete":
            print(f"Deleted {path}")
            return 0
        print(f"Deleted {path}; recording again under the same name.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m cli.record",
        description="Record a mono 44.1 kHz 24-bit WAV take from one input channel.",
    )
    parser.add_argument("--list-devices", action="store_true",
                        help="list input devices and exit")
    parser.add_argument("--device", help="device index or part of its name")
    parser.add_argument("--channel", type=int, help="input channel number (1-based)")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER,
                        help="folder for takes (default: recordings/)")
    parser.add_argument("--name", help="file name prefix instead of 'take'")
    parser.add_argument("--seconds", type=float, help="stop automatically after N seconds")
    parser.add_argument("--keep", action="store_true",
                        help="keep the take without asking")
    parser.add_argument("--config", type=Path, default=aio.DEFAULT_CONFIG_PATH,
                        help="config file (default: local/config.json)")
    args = parser.parse_args(argv)
    if args.seconds is not None and args.seconds <= 0:
        parser.error("--seconds must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    """Entry point: expected errors become one line on stderr and exit code 1."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # device names may not fit the console
        except (AttributeError, ValueError):
            pass
    args = parse_args(argv)
    try:
        return run(args)
    except (aio.AudioIOError, UsageError, FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ncancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
