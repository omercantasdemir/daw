"""Tests for engine.audio_io. They use the fake stream from conftest; no hardware."""

from __future__ import annotations

import builtins
import math
import os
import sys
import time
import warnings
from unittest import mock

import numpy as np
import pytest
import soundfile as sf

from engine import audio_io
from engine.audio_io import (
    DeviceChoice,
    DeviceNotFoundError,
    InputDevice,
    Recorder,
    TakeWarning,
    analyze_take,
    load_config,
    next_take_path,
    order_devices,
    resolve_device,
    save_config,
)

SR = audio_io.SAMPLE_RATE
LSB = 1 / 2**23
UNEVEN_BLOCKS = [1, 37, 512, 1000, 64, 4096, 333]


def sine(freq=440.0, amplitude=0.5, seconds=1.0):
    """A float32 sine of exactly ``seconds * 44100`` frames."""
    t = np.arange(int(round(seconds * SR))) / SR
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def record(path, data, factory, channel=1, overflow_blocks=(), block_sizes=UNEVEN_BLOCKS):
    """Record ``data`` (frames or frames x channels) through a fake stream."""
    data = np.asarray(data, dtype=np.float32)
    channels = 1 if data.ndim == 1 else data.shape[1]
    device = InputDevice(0, "Fake", "Fake API", max(channels, channel), 44100.0)
    with Recorder(path, channel, device, stream_factory=factory) as rec:
        factory.last.feed(data, block_sizes, overflow_blocks)
    return rec.take_info


# 1. Format and sample accuracy -------------------------------------------------


def test_format_and_sample_accuracy(tmp_path, fake_factory):
    source = sine(440.0, 0.5, 1.0)
    path = tmp_path / "take_01.wav"
    info = record(path, source, fake_factory)

    assert fake_factory.last.samplerate == 44100
    data, samplerate = sf.read(path, dtype="float64")
    file_info = sf.info(path)
    assert samplerate == 44100
    assert file_info.channels == 1
    assert file_info.subtype == "PCM_24"
    assert file_info.frames == 44100
    assert len(data) == 44100
    assert info.frames_recorded == 44100
    assert np.max(np.abs(data - source)) <= 2 * LSB


# 2. Channel selection -------------------------------------------------------------


def test_channel_selection_records_only_the_chosen_channel(tmp_path, fake_factory):
    first = sine(440.0, 0.5)
    second = sine(1000.0, 0.25)
    stereo = np.column_stack([first, second])

    path = tmp_path / "ch2.wav"
    record(path, stereo, fake_factory, channel=2)

    assert fake_factory.last.channels == 2
    data, _ = sf.read(path, dtype="float64")
    assert data.ndim == 1
    assert np.max(np.abs(data - second)) <= 2 * LSB
    assert np.max(np.abs(data - first)) > 0.1
    assert np.max(np.abs(data - (first + second) / 2)) > 0.1


# 3. No overwrite --------------------------------------------------------------------


@pytest.mark.parametrize("name, prefix", [(None, "take"), ("riff", "riff")])
def test_no_overwrite(tmp_path, fake_factory, name, prefix):
    folder = tmp_path / "new" / "folder"  # created on demand

    first_path = next_take_path(folder, name)
    assert first_path.name == f"{prefix}_01.wav"
    record(first_path, sine(amplitude=0.3, seconds=0.2), fake_factory)
    first_bytes = first_path.read_bytes()

    second_path = next_take_path(folder, name)
    assert second_path.name == f"{prefix}_02.wav"
    record(second_path, sine(amplitude=0.6, seconds=0.3), fake_factory)

    assert first_path.read_bytes() == first_bytes

    with pytest.raises(FileExistsError):
        Recorder(first_path, 1, stream_factory=fake_factory).start()
    assert first_path.read_bytes() == first_bytes


def test_next_take_path_continues_after_highest_number(tmp_path):
    (tmp_path / "take_07.wav").write_bytes(b"")
    (tmp_path / "take_123.wav").write_bytes(b"")
    (tmp_path / "other_99.wav").write_bytes(b"")
    assert next_take_path(tmp_path).name == "take_124.wav"
    assert next_take_path(tmp_path, "other").name == "other_100.wav"


def test_take_name_must_not_be_a_path(tmp_path):
    with pytest.raises(ValueError):
        next_take_path(tmp_path, "../escape")


# 4. Overflow reporting --------------------------------------------------------------


def test_overflows_are_counted_with_frame_positions(tmp_path, fake_factory):
    blocks = [100, 200, 300]  # block starts: 0, 100, 300, 600, 700, 900, ...
    info = record(tmp_path / "o.wav", sine(seconds=0.1), fake_factory,
                  overflow_blocks={2, 4}, block_sizes=blocks)
    assert info.overflow_count == 2
    assert info.overflow_frames == (300, 700)

    stats = analyze_take(info.path, info.overflow_count)
    assert stats.overflow_count == 2


# 5. Stats and warnings ----------------------------------------------------------------


def amplitude_for(dbfs):
    return 10 ** (dbfs / 20)


def test_full_scale_triggers_clipping(tmp_path, fake_factory):
    info = record(tmp_path / "loud.wav", sine(amplitude=1.0), fake_factory)
    stats = analyze_take(info.path)
    assert TakeWarning.CLIPPING in stats.warnings
    assert TakeWarning.LOW_LEVEL not in stats.warnings
    assert stats.clipped_samples > 0


def test_minus_40_dbfs_triggers_low_level(tmp_path, fake_factory):
    info = record(tmp_path / "quiet.wav", sine(amplitude=amplitude_for(-40)), fake_factory)
    stats = analyze_take(info.path)
    assert stats.warnings == (TakeWarning.LOW_LEVEL,)
    assert stats.peak_dbfs == pytest.approx(-40, abs=0.1)


def test_minus_12_dbfs_triggers_no_warning(tmp_path, fake_factory):
    info = record(tmp_path / "ok.wav", sine(amplitude=amplitude_for(-12)), fake_factory)
    stats = analyze_take(info.path)
    assert stats.warnings == ()
    assert stats.peak_dbfs == pytest.approx(-12, abs=0.1)
    assert stats.rms_dbfs == pytest.approx(-12 - 3.01, abs=0.1)  # sine RMS
    assert stats.clipped_samples == 0
    assert stats.duration_seconds == pytest.approx(1.0)
    assert (stats.samplerate, stats.channels, stats.subtype) == (44100, 1, "PCM_24")


def test_silence_is_negative_infinity_without_numpy_warnings(tmp_path, fake_factory):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with np.errstate(all="raise"):
            info = record(tmp_path / "silence.wav", np.zeros(SR, dtype=np.float32),
                          fake_factory)
            stats = analyze_take(info.path)
            assert audio_io.to_dbfs(0.0) == -math.inf
    assert stats.peak_dbfs == -math.inf
    assert stats.rms_dbfs == -math.inf
    assert TakeWarning.CLIPPING not in stats.warnings


def test_meter_poll_returns_peak_since_last_call(tmp_path, fake_factory):
    device = InputDevice(0, "Fake", "Fake API", 1, 44100.0)
    with Recorder(tmp_path / "m.wav", 1, device, stream_factory=fake_factory) as rec:
        assert rec.poll_peak_dbfs() == -math.inf
        fake_factory.last.feed(sine(amplitude=0.5, seconds=0.1), [441])
        assert rec.poll_peak_dbfs() == pytest.approx(-6.02, abs=0.05)
        assert rec.poll_peak_dbfs() == -math.inf


# 6. Interrupted take ---------------------------------------------------------------------


def test_exception_mid_recording_leaves_valid_wav(tmp_path, fake_factory):
    source = sine(seconds=1.0)
    path = tmp_path / "interrupted.wav"
    device = InputDevice(0, "Fake", "Fake API", 1, 44100.0)
    with pytest.raises(RuntimeError, match="boom"):
        with Recorder(path, 1, device, stream_factory=fake_factory):
            fake_factory.last.feed(source[:10000], UNEVEN_BLOCKS)
            raise RuntimeError("boom")

    assert fake_factory.last.closed
    data, samplerate = sf.read(path, dtype="float64")
    assert samplerate == 44100
    assert len(data) == 10000
    assert np.max(np.abs(data - source[:10000])) <= 2 * LSB


def test_keyboard_interrupt_mid_recording_leaves_valid_wav(tmp_path, fake_factory):
    path = tmp_path / "ctrl_c.wav"
    with pytest.raises(KeyboardInterrupt):
        with Recorder(path, 1, stream_factory=fake_factory):
            fake_factory.last.feed(sine(seconds=0.5), UNEVEN_BLOCKS)
            raise KeyboardInterrupt
    assert sf.info(path).frames == SR // 2


# 7. Config round trip and missing device --------------------------------------------------


def test_config_round_trip(tmp_path):
    path = tmp_path / "local" / "config.json"
    assert load_config(path) is None  # missing file: no choice yet
    choice = DeviceChoice("Focusrite USB ASIO", "ASIO", 2)
    save_config(choice, path)
    assert load_config(path) == choice


def test_resolving_missing_saved_device_raises(tmp_path):
    devices = [InputDevice(3, "Mic", "Windows WASAPI", 2, 48000.0)]
    with pytest.raises(DeviceNotFoundError, match="Focusrite"):
        resolve_device(DeviceChoice("Focusrite USB ASIO", "ASIO", 1), devices)
    # Same name on another host API is a different device.
    with pytest.raises(DeviceNotFoundError):
        resolve_device(DeviceChoice("Mic", "MME", 1), devices)
    # Index does not matter, name + host API does.
    assert resolve_device(DeviceChoice("Mic", "Windows WASAPI", 1), devices).index == 3


def test_device_order_follows_preference_table():
    devices = [
        InputDevice(0, "a", "MME", 2, 44100.0),
        InputDevice(1, "b", "Windows WASAPI", 2, 48000.0),
        InputDevice(2, "c", "ASIO", 2, 44100.0),
        InputDevice(3, "d", "ALSA", 2, 44100.0),
        InputDevice(4, "e", "JACK Audio Connection Kit", 2, 48000.0),
    ]
    assert [d.index for d in order_devices(devices, "win32")] == [2, 1, 0, 3, 4]
    assert [d.index for d in order_devices(devices, "linux")] == [4, 3, 0, 1, 2]
    assert [d.index for d in order_devices(devices, "darwin")] == [0, 1, 2, 3, 4]


# 8. Callback hygiene ------------------------------------------------------------------------


def test_callback_does_no_file_io_printing_or_sleeping(tmp_path, fake_factory):
    def forbidden(name):
        def fail(*args, **kwargs):
            raise AssertionError(f"audio callback called {name}")
        return fail

    def guarded(call):
        with mock.patch.object(builtins, "open", forbidden("open")), \
             mock.patch.object(os, "open", forbidden("os.open")), \
             mock.patch.object(builtins, "print", forbidden("print")), \
             mock.patch.object(builtins, "input", forbidden("input")), \
             mock.patch.object(sys.stdout, "write", forbidden("stdout.write")), \
             mock.patch.object(sys.stderr, "write", forbidden("stderr.write")), \
             mock.patch.object(time, "sleep", forbidden("time.sleep")):
            call()

    device = InputDevice(0, "Fake", "Fake API", 2, 44100.0)
    path = tmp_path / "hygiene.wav"
    with Recorder(path, 2, device, stream_factory=fake_factory) as rec:
        fake_factory.last.callback_wrapper = guarded
        stereo = np.column_stack([sine(seconds=0.2), sine(seconds=0.2)])
        fake_factory.last.feed(stereo, UNEVEN_BLOCKS, overflow_blocks={1})
    assert rec.take_info.frames_recorded == int(0.2 * SR)
    assert rec.take_info.overflow_count == 1
