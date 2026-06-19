"""Whisper-based speech translation via faster-whisper.

With task="translate", Whisper converts speech in (almost) any language directly
into English text in a single pass, and reports the detected source language.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import sys
import sysconfig


def _enable_cuda_dlls():
    """Make pip-installed NVIDIA cuBLAS/cuDNN DLLs discoverable on Windows."""
    if not hasattr(os, "add_dll_directory"):
        return []

    # Collect every plausible site-packages root (works inside a venv too).
    roots = set()
    for key in ("purelib", "platlib"):
        p = sysconfig.get_paths().get(key)
        if p:
            roots.add(p)
    roots.update(p for p in sys.path if p)
    try:
        spec = importlib.util.find_spec("nvidia")
        if spec and spec.submodule_search_locations:
            for loc in spec.submodule_search_locations:
                roots.add(os.path.dirname(loc))  # parent of the `nvidia` pkg dir
    except Exception:  # noqa: BLE001
        pass

    added = []
    for root in roots:
        for path in glob.glob(os.path.join(root, "nvidia", "*", "bin")):
            if os.path.isdir(path):
                try:
                    os.add_dll_directory(path)
                    # Also prepend to PATH as a fallback for older loaders.
                    os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
                    added.append(path)
                except Exception:  # noqa: BLE001
                    pass
    return added


class Transcriber:
    def __init__(self, size="medium", device="auto", compute_type="auto",
                 task="translate", language=None, beam_size=1):
        self.size = size
        self.device = device
        self.compute_type = compute_type
        self.task = task
        self.language = language
        self.beam_size = beam_size
        self.model = None
        self.active_device = None

    def load(self, log=print):
        """Load the model, preferring GPU and falling back to CPU."""
        dll_dirs = _enable_cuda_dlls()
        log(f"[whisper] cuda dll dirs: {len(dll_dirs)} found")
        from faster_whisper import WhisperModel

        attempts = []
        if self.device in ("auto", "cuda"):
            ct = self.compute_type if self.compute_type != "auto" else "float16"
            attempts.append(("cuda", ct))
        if self.device in ("auto", "cpu"):
            # GPU-oriented compute types aren't valid on CPU; fall back to int8.
            ct = self.compute_type
            if ct in ("auto", "float16", "int8_float16"):
                ct = "int8"
            attempts.append(("cpu", ct))

        last_err = None
        for device, compute_type in attempts:
            try:
                log(f"[whisper] loading '{self.size}' on {device} ({compute_type})...")
                self.model = WhisperModel(self.size, device=device,
                                          compute_type=compute_type)
                self.active_device = device
                self._warmup(log)
                log(f"[whisper] ready on {device}.")
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                log(f"[whisper] {device} failed: {e}")
        raise RuntimeError(f"Could not load Whisper model: {last_err}")

    def _warmup(self, log=print):
        """Run one throwaway inference so CUDA kernels compile now, not on the
        user's first real utterance (saves ~2s of latency on the first line)."""
        try:
            import numpy as np
            log("[whisper] warming up…")
            self.translate(np.zeros(16000, dtype=np.float32))
        except Exception as e:  # noqa: BLE001
            log(f"[whisper] warmup skipped: {e}")

    def translate(self, audio):
        """Return (text, language, language_probability) for a float32 16 kHz clip."""
        segments, info = self.model.transcribe(
            audio,
            task=self.task,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=False,            # we already segmented with webrtcvad
            condition_on_previous_text=False,  # faster, avoids drift on short clips
            temperature=0.0,             # greedy, no fallback retries (latency)
            without_timestamps=True,     # skip timestamp decoding (faster)
        )
        text = "".join(seg.text for seg in segments).strip()
        return text, info.language, float(info.language_probability)
