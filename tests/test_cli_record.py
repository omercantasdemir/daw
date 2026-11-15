"""Tests for cli.record: expected errors and an end-to-end take, no hardware."""

from __future__ import annotations

import io
import json

import numpy as np
import pytest
import soundfile as sf

from cli import record
from engine import audio_io as aio

DEVICES = [
    aio.InputDevice(18, "Fake ASIO", "ASIO", 2, 44100.0),
    aio.InputDevice(22, "Fake Mic", "Windows WASAPI", 2, 48000.0),
]


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    """Fake devices, no real format check, empty stdin."""
    monkeypatch.setattr(aio, "list_input_devices_ordered", lambda: list(DEVICES))
    monkeypatch.setattr(aio, "check_format", lambda device, channel: False)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    return tmp_path


class StartFeedsStream:
    """Fake stream that delivers one second of a -6 dBFS sine when started."""

    def __init__(self, *, channels, callback, **kwargs):
        self.channels = channels
        self.callback = callback

    def start(self):
        t = np.arange(aio.SAMPLE_RATE) / aio.SAMPLE_RATE
        signal = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        block = np.repeat(signal[:, None], self.channels, axis=1)
        for start in range(0, len(block), 441):
            chunk = block[start:start + 441]
            self.callback(chunk, len(chunk), None, None)

    def stop(self):
        pass

    def close(self):
        pass


def test_no_input_devices_is_one_line_error(monkeypatch, capsys):
    monkeypatch.setattr(aio, "list_input_devices_ordered", lambda: [])
    assert record.main(["--list-devices"]) == 1
    err = capsys.readouterr().err
    assert err.strip() == "error: no input devices found"


def test_missing_saved_device_is_one_line_error(cli_env, capsys):
    config = cli_env / "config.json"
    aio.save_config(aio.DeviceChoice("Gone Interface", "ASIO", 1), config)
    assert record.main(["--config", str(config), "--seconds", "1", "--keep"]) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith("error: saved device 'Gone Interface'")
    assert "\n" not in err


def test_list_devices(cli_env, capsys):
    assert record.main(["--list-devices"]) == 0
    out = capsys.readouterr().out
    assert "Fake ASIO" in out and "Fake Mic" in out


def test_keep_take_end_to_end(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(aio, "default_stream_factory", StartFeedsStream)
    config = cli_env / "local" / "config.json"
    folder = cli_env / "rec"
    args = ["--device", "asio", "--channel", "2", "--seconds", "0.5", "--keep",
            "--folder", str(folder), "--config", str(config)]

    assert record.main(args) == 0
    assert record.main(args) == 0  # second take must not overwrite the first

    assert sorted(p.name for p in folder.iterdir()) == ["take_01.wav", "take_02.wav"]
    info = sf.info(folder / "take_01.wav")
    assert (info.samplerate, info.channels, info.subtype, info.frames) == (
        44100, 1, "PCM_24", 44100)
    assert json.loads(config.read_text()) == {
        "device_name": "Fake ASIO", "hostapi": "ASIO", "channel": 2}
    out = capsys.readouterr().out
    assert "Using Fake ASIO (ASIO), channel 2" in out
    assert "Peak:      -6.0 dBFS" in out
    assert "Kept" in out


@pytest.mark.parametrize("answer, expected", [("d\n", []), ("r\n", ["take_01.wav"])])
def test_delete_and_redo(cli_env, monkeypatch, answer, expected):
    """Delete removes only this take; redo records again under the same name."""
    monkeypatch.setattr(aio, "default_stream_factory", StartFeedsStream)
    monkeypatch.setattr("sys.stdin", io.StringIO(answer))
    folder = cli_env / "rec"
    folder.mkdir()
    other = folder / "keep_me.wav"
    other.write_bytes(b"not mine to delete")
    args = ["--device", "asio", "--channel", "1", "--seconds", "0.5",
            "--folder", str(folder), "--config", str(cli_env / "c.json")]

    assert record.main(args) == 0
    assert sorted(p.name for p in folder.glob("take_*.wav")) == expected
    assert other.read_bytes() == b"not mine to delete"


def test_unsupported_rate_names_device_and_rate(monkeypatch):
    class FakeSD:
        class PortAudioError(Exception):
            pass

        @staticmethod
        def check_input_settings(**kwargs):
            raise FakeSD.PortAudioError("Invalid sample rate")

    monkeypatch.setattr(aio, "_sd", lambda: FakeSD)
    device = aio.InputDevice(5, "Old Box", "MME", 2, 48000.0)
    with pytest.raises(aio.UnsupportedFormatError, match=r"'Old Box'.*48000 Hz"):
        aio.check_format(device, 1)
