"""Entry point: wires the pipeline to the overlay UI.

Usage:
    python src/main.py                 # run with config.json
    python src/main.py --list-devices  # show loopback capture devices
    python src/main.py --model small   # override model size
    python src/main.py --device cpu    # force CPU
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config import load_config  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Valorant voice-chat translator")
    ap.add_argument("--config", default=None)
    ap.add_argument("--model", default=None, help="override model size")
    ap.add_argument("--device", default=None, choices=["auto", "cuda", "cpu"])
    ap.add_argument("--task", default=None, choices=["translate", "transcribe"])
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()

    if args.list_devices:
        from audio_capture import list_loopback_devices
        print("Available WASAPI loopback devices:")
        print(list_loopback_devices())
        return

    cfg = load_config(args.config)
    if args.model:
        cfg["model"]["size"] = args.model
    if args.device:
        cfg["model"]["device"] = args.device
    if args.task:
        cfg["model"]["task"] = args.task

    from PySide6 import QtWidgets
    from overlay import Bridge, OverlayWindow
    from pipeline import Pipeline

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running via tray when hidden

    bridge = Bridge()
    pipeline_ref = {}

    window = OverlayWindow(
        cfg,
        on_pause_toggle=lambda p: pipeline_ref["p"].set_paused(p),
        on_quit=lambda: pipeline_ref["p"].stop(),
    )
    bridge.result.connect(window.add_result)
    bridge.status.connect(window.set_status)

    pipeline = Pipeline(
        cfg,
        on_result=lambda t, l, pr, partial: bridge.result.emit(t, l, pr, partial),
        on_status=lambda s: bridge.status.emit(s),
    )
    pipeline_ref["p"] = pipeline
    pipeline.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
