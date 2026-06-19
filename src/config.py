"""Configuration loading with sane defaults."""
from __future__ import annotations

import copy
import json
import os

DEFAULTS = {
    "model": {
        "size": "medium",        # tiny / base / small / medium / large-v3
        "path": None,            # local model folder; overrides `size` when set
        "device": "auto",        # auto / cuda / cpu
        "compute_type": "int8_float16",  # auto / float16 / int8_float16 / int8
        "task": "translate",     # translate (-> English) or transcribe (verbatim)
        "language": None,        # None = auto-detect source language
        "beam_size": 1,          # 1 = greedy (fastest), higher = more accurate/slower
    },
    "vad": {
        "aggressiveness": 2,     # 0 (lenient) .. 3 (aggressive) — webrtcvad
        "silence_ms": 400,       # trailing silence that ends an utterance
        "min_speech_ms": 200,    # drop blips shorter than this
        "max_utterance_ms": 8000,
        "pre_pad_ms": 150,       # audio kept before speech starts
        "partial_interval_ms": 700,  # how often to emit a live partial result
    },
    "ui": {
        "mode": "overlay",       # overlay (frameless/translucent) or window
        "opacity": 0.85,
        "font_size": 18,
        "max_lines": 6,
        "width": 620,
        "height": 240,
        "x": 40,
        "y": 40,
        "click_through": False,
        "show_original_lang": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> dict:
    """Load config.json (if present) merged onto DEFAULTS."""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
    user = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
        except Exception as e:  # noqa: BLE001
            print(f"[config] failed to read {path}: {e}; using defaults")
    return _deep_merge(DEFAULTS, user)
