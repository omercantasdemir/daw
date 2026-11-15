"""Audio input: device listing, local device config, format check and the Recorder.

This module never prints and never prompts. It returns plain data (dataclasses,
numbers, paths) or raises exceptions derived from :class:`AudioIOError`.
User interaction lives in ``cli/`` (and later the server).
"""

from __future__ import annotations

import enum
import json
import math
import os
import queue
import re
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import soundfile as sf

# --- Recording format (ARCHITECTURE decision 9) -----------------------------

SAMPLE_RATE = 44100
CHANNELS = 1
SUBTYPE = "PCM_24"
FILE_FORMAT = "WAV"
STREAM_DTYPE = "float32"

# --- Take analysis thresholds ------------------------------------------------

CLIP_SAMPLE_LEVEL = 0.999
"""A sample whose absolute value is at or above this counts as clipped."""

CLIP_PEAK_DBFS = -0.1
"""A take whose peak is above this level gets the clipping warning."""

LOW_LEVEL_PEAK_DBFS = -30.0
"""A take whose peak is below this level gets the low-level warning."""

DEFAULT_CONFIG_PATH = Path("local") / "config.json"
DEFAULT_TAKE_PREFIX = "take"

# --- Host API names as reported by PortAudio ---------------------------------

ASIO = "ASIO"
WASAPI = "Windows WASAPI"
CORE_AUDIO = "Core Audio"
ALSA = "ALSA"
JACK = "JACK Audio Connection Kit"

HOSTAPI_PREFERENCE: dict[str, tuple[str, ...]] = {
    "win32": (ASIO, WASAPI),
    "darwin": (CORE_AUDIO,),
    "linux": (JACK, ALSA),
}
"""Preferred host APIs per platform, best first. Unlisted host APIs come after."""


# --- Exceptions ---------------------------------------------------------------


class AudioIOError(Exception):
    """Base class for expected audio I/O errors (shown to the user as one line)."""


class NoInputDevicesError(AudioIOError):
    """No input device is available."""


class DeviceNotFoundError(AudioIOError):
    """A requested or saved device is not in the current device list."""


class InvalidChannelError(AudioIOError):
    """The requested input channel does not exist on the device."""


class UnsupportedFormatError(AudioIOError):
    """The device does not accept the recording format (44.1 kHz)."""


class ConfigError(AudioIOError):
    """The local config file exists but cannot be read."""


class StreamError(AudioIOError):
    """The input stream could not be opened or started."""


# --- Data ------------------------------------------------------------------------


@dataclass(frozen=True)
class InputDevice:
    """An input-capable audio device as seen in the current session."""

    index: int
    name: str
    hostapi: str
    max_input_channels: int
    default_samplerate: float


@dataclass(frozen=True)
class DeviceChoice:
    """A saved device choice. Identified by name + host API, never by index."""

    device_name: str
    hostapi: str
    channel: int


class TakeWarning(enum.Enum):
    """Warnings about a take, returned as data."""

    CLIPPING = "clipping"
    LOW_LEVEL = "low_level"


@dataclass(frozen=True)
class TakeInfo:
    """What the Recorder knows about a finished take."""

    path: Path
    frames_recorded: int
    overflow_count: int
    overflow_frames: tuple[int, ...]
    wasapi_auto_convert: bool
    channel: int
    device_name: str | None
    hostapi: str | None


@dataclass(frozen=True)
class TakeStats:
    """Stats of a take, computed by re-reading the saved file from disk."""

    path: Path
    duration_seconds: float
    frames: int
    samplerate: int
    channels: int
    subtype: str
    peak_dbfs: float
    rms_dbfs: float
    clipped_samples: int
    overflow_count: int
    warnings: tuple[TakeWarning, ...]


# --- sounddevice access --------------------------------------------------------


def _sd() -> Any:
    """Import sounddevice lazily, with ASIO enabled on Windows.

    sounddevice 0.5.x loads its ASIO-enabled PortAudio build only when the
    ``SD_ENABLE_ASIO`` environment variable is set before the first import.
    An existing value set by the user is respected.
    """
    if sys.platform == "win32":
        os.environ.setdefault("SD_ENABLE_ASIO", "1")
    import sounddevice

    return sounddevice


# --- Levels ------------------------------------------------------------------------


def to_dbfs(amplitude: float) -> float:
    """Convert a linear amplitude (1.0 = full scale) to dBFS.

    Digital silence (0 or below) returns negative infinity without warnings.
    """
    if amplitude <= 0.0:
        return -math.inf
    return 20.0 * math.log10(amplitude)


# --- Devices -----------------------------------------------------------------------


def list_input_devices() -> list[InputDevice]:
    """Return all devices with at least one input channel, in PortAudio order."""
    sd = _sd()
    hostapis = sd.query_hostapis()
    devices = []
    for raw in sd.query_devices():
        if raw["max_input_channels"] < 1:
            continue
        devices.append(
            InputDevice(
                index=int(raw["index"]),
                name=str(raw["name"]),
                hostapi=str(hostapis[raw["hostapi"]]["name"]),
                max_input_channels=int(raw["max_input_channels"]),
                default_samplerate=float(raw["default_samplerate"]),
            )
        )
    return devices


def _platform_key(platform: str) -> str:
    """Map ``sys.platform`` values to keys of :data:`HOSTAPI_PREFERENCE`."""
    return "linux" if platform.startswith("linux") else platform


def order_devices(
    devices: Iterable[InputDevice], platform: str | None = None
) -> list[InputDevice]:
    """Return devices ordered by host API preference for the platform.

    The order within one host API is kept (stable sort).
    """
    preference = HOSTAPI_PREFERENCE.get(_platform_key(platform or sys.platform), ())

    def rank(device: InputDevice) -> int:
        try:
            return preference.index(device.hostapi)
        except ValueError:
            return len(preference)

    return sorted(devices, key=rank)


def list_input_devices_ordered() -> list[InputDevice]:
    """Return input devices ordered by host API preference for this platform."""
    return order_devices(list_input_devices())


def resolve_device(choice: DeviceChoice, devices: Sequence[InputDevice]) -> InputDevice:
    """Find the device of a saved choice by name + host API.

    Raises:
        DeviceNotFoundError: the saved device is not connected / not listed.
    """
    for device in devices:
        if device.name == choice.device_name and device.hostapi == choice.hostapi:
            return device
    raise DeviceNotFoundError(
        f"saved device '{choice.device_name}' ({choice.hostapi}) is not available; "
        "connect it or choose another device with --device"
    )


def select_device(spec: str, devices: Sequence[InputDevice]) -> InputDevice:
    """Pick a device by PortAudio index (digits) or case-insensitive name substring.

    For a substring, the first match in ``devices`` wins, so pass an ordered
    list to prefer the best host API.

    Raises:
        DeviceNotFoundError: nothing matches.
    """
    spec = spec.strip()
    if spec.isdigit():
        index = int(spec)
        for device in devices:
            if device.index == index:
                return device
        raise DeviceNotFoundError(f"no input device with index {index}")
    needle = spec.casefold()
    for device in devices:
        if needle in device.name.casefold():
            return device
    raise DeviceNotFoundError(f"no input device matching '{spec}'")


def validate_channel(device: InputDevice, channel: int) -> None:
    """Check a 1-based input channel number against the device.

    Raises:
        InvalidChannelError: channel is below 1 or above the device's inputs.
    """
    if not 1 <= channel <= device.max_input_channels:
        raise InvalidChannelError(
            f"channel {channel} is not valid for '{device.name}' "
            f"({device.max_input_channels} input channel(s))"
        )


# --- Local config ----------------------------------------------------------------


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> DeviceChoice | None:
    """Load the saved device choice. A missing file means "no choice yet" (None).

    Raises:
        ConfigError: the file exists but is not a valid config.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        # utf-8-sig: accept a BOM, which some Windows editors add.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return DeviceChoice(
            device_name=str(data["device_name"]),
            hostapi=str(data["hostapi"]),
            channel=int(data["channel"]),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc


def save_config(choice: DeviceChoice, path: Path | str = DEFAULT_CONFIG_PATH) -> None:
    """Save the device choice as JSON, creating the parent folder if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(choice), indent=2) + "\n", encoding="utf-8")


# --- Format check ------------------------------------------------------------------


def check_format(device: InputDevice, channel: int) -> bool:
    """Verify the device accepts 44100 Hz float input on the chosen channel.

    The stream is opened with ``channel`` channels (channel N is the last one),
    so that is what gets checked. On WASAPI, if the plain check fails, the
    check is repeated with WASAPI automatic sample-rate conversion
    (``WasapiSettings(auto_convert=True)``, shared mode only).

    Returns:
        True if WASAPI auto conversion is needed, False otherwise. Pass it on
        to :class:`Recorder` so the take info records it.

    Raises:
        InvalidChannelError: the channel does not exist on the device.
        UnsupportedFormatError: the device does not accept 44100 Hz.
    """
    validate_channel(device, channel)
    sd = _sd()
    settings = dict(
        device=device.index, channels=channel, dtype=STREAM_DTYPE, samplerate=SAMPLE_RATE
    )
    try:
        sd.check_input_settings(**settings)
        return False
    except (sd.PortAudioError, ValueError) as exc:
        reason = exc
    if device.hostapi == WASAPI:
        try:
            sd.check_input_settings(
                **settings, extra_settings=sd.WasapiSettings(auto_convert=True)
            )
            return True
        except (sd.PortAudioError, ValueError):
            pass
    raise UnsupportedFormatError(
        f"'{device.name}' ({device.hostapi}) does not accept {SAMPLE_RATE} Hz on "
        f"channel {channel}; it supports {device.default_samplerate:g} Hz ({reason})"
    )


# --- Take files ----------------------------------------------------------------------


def next_take_path(folder: Path | str, name: str | None = None) -> Path:
    """Return the next free ``<name>_NN.wav`` path in ``folder``.

    ``name`` defaults to ``take``. NN is one more than the highest number
    already in the folder, at least two digits. The folder is created if
    missing. The file itself is not created here; :class:`Recorder` creates
    it in exclusive mode, so a race can never overwrite an existing file.
    """
    prefix = name if name else DEFAULT_TAKE_PREFIX
    if Path(prefix).name != prefix or prefix in (".", ".."):
        raise ValueError(f"take name must not contain a path: {prefix!r}")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(re.escape(prefix) + r"_(\d+)\.wav", re.IGNORECASE)
    highest = 0
    for entry in folder.iterdir():
        match = pattern.fullmatch(entry.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return folder / f"{prefix}_{highest + 1:02d}.wav"


def analyze_take(path: Path | str, overflow_count: int = 0) -> TakeStats:
    """Compute take stats by re-reading the WAV file from disk.

    ``overflow_count`` comes from :class:`TakeInfo`; it cannot be seen in
    the file itself.
    """
    path = Path(path)
    peak = 0.0
    sum_squares = 0.0
    clipped = 0
    with sf.SoundFile(path) as wav:
        frames = wav.frames
        samplerate = wav.samplerate
        channels = wav.channels
        subtype = wav.subtype
        for block in wav.blocks(blocksize=65536, dtype="float64", always_2d=True):
            magnitude = np.abs(block)
            if magnitude.size:
                peak = max(peak, float(magnitude.max()))
                sum_squares += float(np.dot(magnitude.ravel(), magnitude.ravel()))
                clipped += int(np.count_nonzero(magnitude >= CLIP_SAMPLE_LEVEL))
    samples = frames * channels
    rms = math.sqrt(sum_squares / samples) if samples else 0.0
    peak_dbfs = to_dbfs(peak)

    warnings = []
    if clipped > 0 or peak_dbfs > CLIP_PEAK_DBFS:
        warnings.append(TakeWarning.CLIPPING)
    if peak_dbfs < LOW_LEVEL_PEAK_DBFS:
        warnings.append(TakeWarning.LOW_LEVEL)

    return TakeStats(
        path=path,
        duration_seconds=frames / samplerate if samplerate else 0.0,
        frames=frames,
        samplerate=samplerate,
        channels=channels,
        subtype=subtype,
        peak_dbfs=peak_dbfs,
        rms_dbfs=to_dbfs(rms),
        clipped_samples=clipped,
        overflow_count=overflow_count,
        warnings=tuple(warnings),
    )


# --- Recorder --------------------------------------------------------------------------

StreamFactory = Callable[..., Any]
"""Creates an input stream. Called with keyword arguments ``device`` (index or
None), ``channels``, ``samplerate``, ``dtype``, ``blocksize``, ``callback`` and
``wasapi_auto_convert`` (bool). The returned object needs ``start()``,
``stop()`` and ``close()``. The callback has the sounddevice signature
``callback(indata, frames, time, status)``; ``status.input_overflow`` is read."""


def default_stream_factory(
    *,
    device: int | None,
    channels: int,
    samplerate: int,
    dtype: str,
    blocksize: int,
    callback: Callable[..., None],
    wasapi_auto_convert: bool,
) -> Any:
    """Create a real ``sounddevice.InputStream``."""
    sd = _sd()
    extra = sd.WasapiSettings(auto_convert=True) if wasapi_auto_convert else None
    return sd.InputStream(
        device=device,
        channels=channels,
        samplerate=samplerate,
        dtype=dtype,
        blocksize=blocksize,
        callback=callback,
        extra_settings=extra,
    )


_STOP = None  # writer-thread sentinel


class Recorder:
    """Record one input channel to a new mono 44.1 kHz 24-bit WAV file.

    One Recorder records one take. Typical use::

        fmt = check_format(device, channel)
        with Recorder(path, channel, device, wasapi_auto_convert=fmt) as rec:
            ...  # poll rec.poll_peak_dbfs() for a meter
        info = rec.take_info

    The audio callback only copies the chosen channel, queues it, updates the
    meter peak and notes overflows. A writer thread drains the queue to disk.
    :meth:`stop` always leaves a valid, closed WAV file, also after an
    exception or Ctrl+C inside the ``with`` block.
    """

    def __init__(
        self,
        path: Path | str,
        channel: int,
        device: InputDevice | None = None,
        *,
        wasapi_auto_convert: bool = False,
        stream_factory: StreamFactory | None = None,
        blocksize: int = 0,
    ) -> None:
        """
        Args:
            path: output file; must not exist (it is created in exclusive mode).
            channel: 1-based input channel number to record.
            device: input device, or None for the system default input.
            wasapi_auto_convert: result of :func:`check_format`.
            stream_factory: stream creator, injectable for tests.
            blocksize: frames per callback; 0 lets the host API choose.
        """
        if channel < 1:
            raise InvalidChannelError(f"channel must be 1 or higher, got {channel}")
        if device is not None:
            validate_channel(device, channel)
        self.path = Path(path)
        self.channel = channel
        self.device = device
        self.wasapi_auto_convert = wasapi_auto_convert
        self._stream_factory = stream_factory or default_stream_factory
        self._blocksize = blocksize

        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._column = channel - 1
        self._frames_received = 0
        self._meter_peak = 0.0
        self._overflow_frames: list[int] = []

        self._file = None
        self._wav: sf.SoundFile | None = None
        self._stream = None
        self._writer: threading.Thread | None = None
        self._writer_error: BaseException | None = None
        self._frames_written = 0
        self._started = False
        self._stopped = False
        self._take_info: TakeInfo | None = None

    # -- audio callback (real-time: no file I/O, no printing, no blocking) --

    def _callback(self, indata: np.ndarray, frames: int, time: Any, status: Any) -> None:
        """Copy the chosen channel to the queue; update meter and overflow list."""
        if status is not None and status.input_overflow:
            self._overflow_frames.append(self._frames_received)
        block = indata[:, self._column].copy()
        self._frames_received += frames
        if frames:
            peak = float(np.abs(block).max())
            if peak > self._meter_peak:
                self._meter_peak = peak
        self._queue.put_nowait(block)

    # -- writer thread --

    def _write_loop(self) -> None:
        """Drain the queue into the WAV file until the stop sentinel arrives."""
        while True:
            block = self._queue.get()
            if block is _STOP:
                return
            if self._writer_error is not None:
                continue  # keep draining so memory does not grow
            try:
                self._wav.write(block)
                self._frames_written += len(block)
            except BaseException as exc:  # reported by stop()
                self._writer_error = exc

    # -- public interface --

    def start(self) -> None:
        """Create the output file (exclusive) and start recording.

        The stream is created (not started) before the file, so a device that
        cannot be opened leaves no file behind.

        Raises:
            FileExistsError: the output path already exists.
            StreamError: the input stream could not be opened or started.
                If it fails only at start, the file is closed as a valid,
                empty WAV.
            RuntimeError: the recorder was already started.
        """
        if self._started:
            raise RuntimeError("a Recorder records one take; create a new one")
        self._started = True
        if self.path.exists():
            self._stopped = True
            raise FileExistsError(f"refusing to overwrite existing file: {self.path}")
        try:
            try:
                self._stream = self._stream_factory(
                    device=self.device.index if self.device else None,
                    channels=self.channel,
                    samplerate=SAMPLE_RATE,
                    dtype=STREAM_DTYPE,
                    blocksize=self._blocksize,
                    callback=self._callback,
                    wasapi_auto_convert=self.wasapi_auto_convert,
                )
            except Exception as exc:
                raise StreamError(f"cannot open input stream: {exc}") from exc
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, "xb")  # exclusive: never overwrites
            self._wav = sf.SoundFile(
                self._file,
                mode="w",
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                subtype=SUBTYPE,
                format=FILE_FORMAT,
            )
            self._writer = threading.Thread(
                target=self._write_loop, name="recorder-writer", daemon=True
            )
            self._writer.start()
            try:
                self._stream.start()
            except Exception as exc:
                raise StreamError(f"cannot start input stream: {exc}") from exc
        except BaseException:
            try:
                self.stop()
            except BaseException:
                pass  # report the original error
            raise

    def stop(self) -> TakeInfo:
        """Stop recording, flush and close the file. Safe to call more than once.

        Returns:
            The take info. Overflows are always included.

        Raises:
            The first error from the stream or the writer, after the file has
            been closed.
        """
        if self._stopped:
            return self._take_info
        self._stopped = True
        errors: list[BaseException] = []

        if self._stream is not None:
            for action in (self._stream.stop, self._stream.close):
                try:
                    action()
                except BaseException as exc:
                    errors.append(exc)
        if self._writer is not None:
            self._queue.put(_STOP)
            self._writer.join()
            if self._writer_error is not None:
                errors.append(self._writer_error)
        for closable in (self._wav, self._file):
            if closable is not None:
                try:
                    closable.close()
                except BaseException as exc:
                    errors.append(exc)

        self._take_info = TakeInfo(
            path=self.path,
            frames_recorded=self._frames_written,
            overflow_count=len(self._overflow_frames),
            overflow_frames=tuple(self._overflow_frames),
            wasapi_auto_convert=self.wasapi_auto_convert,
            channel=self.channel,
            device_name=self.device.name if self.device else None,
            hostapi=self.device.hostapi if self.device else None,
        )
        if errors:
            raise errors[0]
        return self._take_info

    @property
    def take_info(self) -> TakeInfo | None:
        """Take info after :meth:`stop`, else None."""
        return self._take_info

    @property
    def elapsed_seconds(self) -> float:
        """Seconds of audio received so far."""
        return self._frames_received / SAMPLE_RATE

    @property
    def overflow_count(self) -> int:
        """Number of input overflows so far."""
        return len(self._overflow_frames)

    def poll_peak_dbfs(self) -> float:
        """Return the peak in dBFS since the last call and reset it.

        Meant for a UI meter polled a few times per second. No lock is used
        (the callback must never wait), so a block arriving exactly during
        the reset can be missed by the meter; the file is unaffected.
        """
        peak = self._meter_peak
        self._meter_peak = 0.0
        return to_dbfs(peak)

    def __enter__(self) -> "Recorder":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.stop()
            return
        try:
            self.stop()
        except BaseException:
            pass  # the original exception is more important
