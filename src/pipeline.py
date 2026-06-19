"""Orchestrates capture -> segmentation -> translation across worker threads."""
from __future__ import annotations

import queue
import threading

from audio_capture import AudioCapture
from transcriber import Transcriber
from vad_segmenter import Segmenter


class Pipeline:
    def __init__(self, cfg: dict, on_result, on_status=print):
        self.cfg = cfg
        self.on_result = on_result      # (text, lang, prob)
        self.on_status = on_status      # (str)

        self.capture = AudioCapture()
        v = cfg["vad"]
        self.segmenter = Segmenter(
            aggressiveness=v["aggressiveness"],
            silence_ms=v["silence_ms"],
            min_speech_ms=v["min_speech_ms"],
            max_utterance_ms=v["max_utterance_ms"],
            pre_pad_ms=v["pre_pad_ms"],
            partial_interval_ms=v.get("partial_interval_ms", 700),
        )
        m = cfg["model"]
        self.transcriber = Transcriber(
            size=(m.get("path") or m["size"]),
            device=m["device"], compute_type=m["compute_type"],
            task=m["task"], language=m["language"], beam_size=m["beam_size"],
        )

        self.utt_q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._paused = threading.Event()

    def set_paused(self, paused: bool):
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    def start(self):
        threading.Thread(target=self._boot, daemon=True).start()

    def _boot(self):
        try:
            self.transcriber.load(log=self.on_status)
        except Exception as e:  # noqa: BLE001
            self.on_status(f"Model load failed: {e}")
            return
        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._transcribe_loop, daemon=True).start()
        self.on_status(f"Listening… ({self.transcriber.active_device}, "
                       f"src: {self.capture.device_name})")

    def _capture_loop(self):
        try:
            for frame in self.capture.frames():
                if self._stop.is_set():
                    break
                if self._paused.is_set():
                    continue
                event = self.segmenter.process(frame)
                if event is not None:
                    self.utt_q.put(event)
        except Exception as e:  # noqa: BLE001
            self.on_status(f"Audio capture error: {e}")

    def _transcribe_loop(self):
        while not self._stop.is_set():
            try:
                first = self.utt_q.get(timeout=0.3)
            except queue.Empty:
                continue

            # Drain everything queued and coalesce: process all 'final' events
            # in order, but only the single most recent 'partial' (older partials
            # are stale). This keeps live text fresh instead of lagging behind.
            batch = [first]
            try:
                while True:
                    batch.append(self.utt_q.get_nowait())
            except queue.Empty:
                pass

            for kind, audio in batch:
                if kind == "final":
                    self._emit(audio, is_partial=False)
            if batch[-1][0] == "partial":
                self._emit(batch[-1][1], is_partial=True)

    def _emit(self, audio, is_partial):
        try:
            text, lang, prob = self.transcriber.translate(audio)
        except Exception as e:  # noqa: BLE001
            text, lang, prob = f"[error: {e}]", "?", 0.0
        if text:
            self.on_result(text, lang, prob, is_partial)

    def stop(self):
        self._stop.set()
        self.capture.stop()
