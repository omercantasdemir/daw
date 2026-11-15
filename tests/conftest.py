"""Shared test helpers: a fake input stream that needs no audio hardware."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest


@dataclass
class FakeStatus:
    """Stand-in for ``sounddevice.CallbackFlags``."""

    input_overflow: bool = False


class FakeStream:
    """Fake input stream. Tests push audio through the callback with :meth:`feed`."""

    def __init__(self, *, device, channels, samplerate, dtype, blocksize, callback,
                 wasapi_auto_convert):
        self.device = device
        self.channels = channels
        self.samplerate = samplerate
        self.dtype = dtype
        self.callback = callback
        self.wasapi_auto_convert = wasapi_auto_convert
        self.started = False
        self.closed = False
        self.callback_wrapper = None  # optional: fn(call) used around each callback

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def feed(self, data: np.ndarray, block_sizes, overflow_blocks=()):
        """Send ``data`` (frames x channels) through the callback.

        ``block_sizes`` is cycled until all frames are sent. Blocks whose
        index is in ``overflow_blocks`` carry the input-overflow flag.
        """
        data = np.asarray(data, dtype=np.float32)
        if data.ndim == 1:
            data = data[:, None]
        assert data.shape[1] == self.channels, "fake data must match stream channels"
        position, block_index = 0, 0
        while position < len(data):
            size = block_sizes[block_index % len(block_sizes)]
            block = np.ascontiguousarray(data[position:position + size])
            status = FakeStatus(input_overflow=block_index in overflow_blocks)

            def call(block=block, status=status):
                self.callback(block, len(block), None, status)

            if self.callback_wrapper is None:
                call()
            else:
                self.callback_wrapper(call)
            position += len(block)
            block_index += 1


class FakeStreamFactory:
    """Stream factory that remembers the streams it created."""

    def __init__(self):
        self.streams: list[FakeStream] = []

    def __call__(self, **kwargs):
        stream = FakeStream(**kwargs)
        self.streams.append(stream)
        return stream

    @property
    def last(self) -> FakeStream:
        return self.streams[-1]


@pytest.fixture
def fake_factory():
    return FakeStreamFactory()
