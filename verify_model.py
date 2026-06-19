"""Verify a locally-downloaded faster-whisper model loads and runs.

Usage:
    python verify_model.py models\faster-whisper-medium
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import numpy as np  # noqa: E402
from transcriber import Transcriber  # noqa: E402

REQUIRED = ["model.bin", "config.json", "tokenizer.json"]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else r"models\faster-whisper-medium"
    path = os.path.abspath(path)
    print(f"Checking folder: {path}")
    if not os.path.isdir(path):
        print("  !! folder does not exist")
        return
    files = os.listdir(path)
    print("  files:", files)
    missing = [f for f in REQUIRED if f not in files]
    if missing:
        print(f"  !! missing required files: {missing}")
        print("     (download every file from the HF repo into this folder)")
        return

    t = Transcriber(size=path, device="auto")
    t0 = time.time()
    t.load()
    print(f"  loaded in {time.time()-t0:.1f}s on {t.active_device}")

    audio = np.zeros(16000 * 2, dtype=np.float32)  # 2s silence, just exercises inference
    t0 = time.time()
    text, lang, prob = t.translate(audio)
    print(f"  inference ran in {time.time()-t0:.2f}s (lang={lang}, text={text!r})")
    print("  OK — model works. Set this path as model.path in config.json.")


if __name__ == "__main__":
    main()
