"""WASAPI loopback audio capture.

Captures whatever is playing on the default output device (i.e. the game,
including Valorant's voice chat) WITHOUT touching the game process. This is an
OS-level capture and is invisible to anti-cheat — no injection, no hooking.

Output: a stream of fixed-size float32 frames at 16 kHz mono, which is exactly
what both webrtcvad and Whisper expect.
"""
from __future__ import annotations

import threading

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

TARGET_RATE = 16000
FRAME_MS = 30  # webrtcvad accepts 10/20/30 ms frames
FRAME_SAMPLES = int(TARGET_RATE * FRAME_MS / 1000)  # 480 samples


class AudioCapture:
    def __init__(self, frame_ms: int = FRAME_MS):
        self.frame_ms = frame_ms
        self.frame_samples = int(TARGET_RATE * frame_ms / 1000)
        self._stop = threading.Event()
        self._pa: pyaudio.PyAudio | None = None
        self._stream = None
        self.device_name = "?"
        self.native_rate = 0
        self.channels = 0

    def _open(self):
        self._pa = pyaudio.PyAudio()
        # Default output device, captured in loopback mode.
        dev = self._pa.get_default_wasapi_loopback()
        self.device_name = dev["name"]
        self.native_rate = int(dev["defaultSampleRate"])
        self.channels = int(dev["maxInputChannels"]) or 2
        block = int(round(self.native_rate * self.frame_ms / 1000))
        self._block = block
        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.native_rate,
            input=True,
            frames_per_buffer=block,
            input_device_index=dev["index"],
        )

    def frames(self):
        """Generator yielding float32 arrays of length frame_samples @ 16 kHz mono."""
        self._open()
        try:
            while not self._stop.is_set():
                raw = self._stream.read(self._block, exception_on_overflow=False)
                data = np.frombuffer(raw, dtype=np.float32)
                if self.channels > 1:
                    data = data.reshape(-1, self.channels).mean(axis=1)
                if self.native_rate != TARGET_RATE:
                    data = resample_poly(data, TARGET_RATE, self.native_rate)
                # Force exact frame length for webrtcvad.
                if len(data) < self.frame_samples:
                    data = np.pad(data, (0, self.frame_samples - len(data)))
                elif len(data) > self.frame_samples:
                    data = data[: self.frame_samples]
                yield data.astype(np.float32)
        finally:
            self._close()

    def stop(self):
        self._stop.set()

    def _close(self):
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._pa is not None:
                self._pa.terminate()
        except Exception:  # noqa: BLE001
            pass


def list_loopback_devices() -> str:
    """Return a human-readable list of available loopback devices (for debugging)."""
    pa = pyaudio.PyAudio()
    lines = []
    try:
        for info in pa.get_loopback_device_info_generator():
            lines.append(f"  [{info['index']}] {info['name']} "
                         f"({int(info['defaultSampleRate'])} Hz, "
                         f"{int(info['maxInputChannels'])} ch)")
    finally:
        pa.terminate()
    return "\n".join(lines) if lines else "  (none found)"
