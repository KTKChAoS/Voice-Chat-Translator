# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is
A real-time translator for in-game voice chat (built for **Valorant**, works with
any source). It captures system audio, runs speech-to-text/translation with
faster-whisper, and shows live English text in an overlay. Everything runs
**locally on the GPU** — no cloud.

## ⛔ Hard constraint: stay external to the game (anti-cheat)
Valorant runs **Riot Vanguard**, a kernel-level anti-cheat. This project is
deliberately external and must stay that way:
- **Capture audio only via WASAPI loopback** (OS-level). Never read game memory,
  hook the game, or inject anything.
- **Display in a separate top-level window only.** Never draw into the game's
  DirectX/render pipeline (no overlay injection).
- Avoid global low-level input hooks where possible; tray-icon controls are
  preferred over keyboard hooks.

If a feature request would require any of the above, flag it and propose an
external alternative instead.

## Environment
- **OS:** Windows 11. Shell is PowerShell; a Bash tool is also available.
- **GPU:** NVIDIA RTX 3060 Laptop (6 GB). Shares VRAM with Valorant, so keep the
  model footprint small (`int8_float16` ≈ 1.5 GB for medium).
- **Python:** 3.11, in a venv at `.venv`. **Always use the venv interpreter:**
  `\.venv\Scripts\python.exe` (not bare `python`).
- Not a git repo.

## Run / test commands
```powershell
.\.venv\Scripts\python.exe src\main.py                 # run the app (GUI)
.\.venv\Scripts\python.exe src\main.py --list-devices  # list loopback devices
.\.venv\Scripts\python.exe verify_model.py models\faster-whisper-medium
.\.venv\Scripts\python.exe test_audio.py               # audio-level meter (play sound)
.\.venv\Scripts\python.exe -m py_compile src\*.py      # quick syntax check
```
The GUI opens a real window on the user's desktop — prefer asking the user to run
`src\main.py` and report behavior rather than launching it from a tool.

## Architecture (see docs/ARCHITECTURE.md for detail)
Three stages across worker threads, glued by `pipeline.py`:
1. `audio_capture.py` — WASAPI loopback (default output device) → fixed 30 ms /
   16 kHz mono float32 frames (resampled with `scipy.signal.resample_poly`).
2. `vad_segmenter.py` — webrtcvad turns frames into events:
   `("partial", audio)` periodically while speech continues, `("final", audio)`
   on a pause. Streaming partials are what make latency feel ~1s.
3. `transcriber.py` — faster-whisper `transcribe(task="translate")`; returns
   `(text, language, prob)`.

`pipeline.py` runs a capture thread and a transcribe thread. The transcribe loop
**coalesces** the queue: it processes all `final` events but only the *latest*
`partial` (stale partials are dropped) so live text never lags.

`overlay.py` is a frameless translucent `QTextEdit` (auto-scrolls to newest line)
with a `QSystemTrayIcon` menu. Worker threads talk to the UI only through
`Bridge` Qt signals — never touch widgets from a worker thread.

## Gotchas / things that already bit us
- **Hugging Face is blocked for programmatic requests** on this machine (TLS
  reset), even though the browser works. Models are therefore **downloaded
  manually by the user into `models/<name>/`** and loaded via `model.path`. Do
  not reintroduce auto-download as the primary path.
- **CUDA DLLs**: faster-whisper needs cuBLAS/cuDNN DLLs that pip installs under
  `.venv/Lib/site-packages/nvidia/*/bin`. `transcriber._enable_cuda_dlls()` adds
  these to the DLL search path; without it you get
  `cublas64_12.dll not found`. Don't remove it. It scans `sysconfig` paths +
  `sys.path` + the `nvidia` package location (venv-safe).
- **CPU fallback** must not inherit a GPU-only `compute_type` (`float16` /
  `int8_float16`); `transcriber.load()` downgrades it to `int8`.
- **Warmup**: `transcriber._warmup()` runs one throwaway inference on load so the
  user's first real line isn't slowed ~2s by CUDA kernel compilation.
- **VAD frame size is exact**: webrtcvad requires precisely 10/20/30 ms frames;
  capture pads/trims every frame to 480 samples. Keep that invariant.

## Conventions
- Keep it dependency-light and Windows-first. Match the existing terse,
  comment-the-why style.
- Config changes go in **both** `config.json` and the `DEFAULTS` in
  `src/config.py` (deep-merged).
- After editing, `py_compile` the changed files. For logic changes, prefer a
  small headless test (like the segmenter event-sequence check) over launching
  the GUI.
