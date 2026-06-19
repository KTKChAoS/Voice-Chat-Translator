"""Voice-activity-based segmentation.

Consumes fixed 30 ms / 16 kHz frames and emits complete utterances (numpy
float32 arrays) once a speaker pauses. We segment ourselves rather than feeding
a continuous stream to Whisper so that translations appear utterance-by-utterance
with low latency.
"""
from __future__ import annotations

import collections

import numpy as np
import webrtcvad

from audio_capture import FRAME_MS, TARGET_RATE


class Segmenter:
    def __init__(
        self,
        aggressiveness: int = 2,
        silence_ms: int = 400,
        min_speech_ms: int = 200,
        max_utterance_ms: int = 8000,
        pre_pad_ms: int = 150,
        partial_interval_ms: int = 700,
        sample_rate: int = TARGET_RATE,
        frame_ms: int = FRAME_MS,
    ):
        self.vad = webrtcvad.Vad(aggressiveness)
        self.sr = sample_rate
        self.frame_ms = frame_ms
        self.silence_frames = max(1, silence_ms // frame_ms)
        self.min_speech_frames = max(1, min_speech_ms // frame_ms)
        self.max_frames = max(1, max_utterance_ms // frame_ms)
        self.pre_pad_frames = max(0, pre_pad_ms // frame_ms)
        self.partial_interval_frames = max(1, partial_interval_ms // frame_ms)
        self._reset()

    def _reset(self):
        self.triggered = False
        self.frames: list[np.ndarray] = []
        self.speech_frames = 0
        self.silence_count = 0
        self.frames_since_partial = 0
        self.prebuf = collections.deque(maxlen=self.pre_pad_frames)

    def process(self, frame: np.ndarray):
        """Feed one frame. Returns ('partial'|'final', audio) or None.

        'partial' fires periodically while someone is still speaking (live,
        will be refined); 'final' fires once they pause.
        """
        pcm16 = (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16)
        try:
            speech = self.vad.is_speech(pcm16.tobytes(), self.sr)
        except Exception:  # noqa: BLE001 — bad frame length etc.
            speech = False

        if not self.triggered:
            self.prebuf.append(frame)
            if speech:
                self.triggered = True
                self.frames = list(self.prebuf)
                self.prebuf.clear()
                self.speech_frames = 1
                self.silence_count = 0
                self.frames_since_partial = 0
            return None

        # Currently inside an utterance.
        self.frames.append(frame)
        self.frames_since_partial += 1
        if speech:
            self.speech_frames += 1
            self.silence_count = 0
        else:
            self.silence_count += 1

        ended = self.silence_count >= self.silence_frames
        too_long = len(self.frames) >= self.max_frames
        if ended or too_long:
            out = None
            if self.speech_frames >= self.min_speech_frames:
                out = ("final", np.concatenate(self.frames).astype(np.float32))
            self._reset()
            return out

        # Emit a live partial every partial_interval while speech is ongoing.
        if (self.speech_frames >= self.min_speech_frames
                and self.frames_since_partial >= self.partial_interval_frames):
            self.frames_since_partial = 0
            return ("partial", np.concatenate(self.frames).astype(np.float32))
        return None
