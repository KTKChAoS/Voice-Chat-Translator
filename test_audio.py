"""Quick audio-capture meter. Play any sound while this runs to see levels."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import numpy as np  # noqa: E402
from audio_capture import AudioCapture  # noqa: E402
from vad_segmenter import Segmenter  # noqa: E402

cap = AudioCapture()
seg = Segmenter()
gen = cap.frames()
print(f"Capturing from: {cap.device_name if cap.device_name != '?' else '(opening...)'}")

start = time.time()
peak = 0.0
voiced_frames = 0
utterances = 0
try:
    for frame in gen:
        rms = float(np.sqrt(np.mean(frame ** 2)))
        peak = max(peak, rms)
        bar = "#" * min(40, int(rms * 400))
        print(f"\rlevel |{bar:<40}| rms={rms:.4f}", end="")
        if seg.process(frame) is not None:
            utterances += 1
        if time.time() - start > 6:
            break
finally:
    cap.stop()

print(f"\n\nDevice: {cap.device_name} ({cap.native_rate} Hz, {cap.channels} ch)")
print(f"Peak RMS over 6s: {peak:.4f}")
print(f"Detected utterances: {utterances}")
if peak < 0.0005:
    print("=> Near silence. Either nothing was playing, or game audio is on a")
    print("   DIFFERENT output device than the Windows default.")
else:
    print("=> Audio captured successfully.")
