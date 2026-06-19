# Architecture

How the translator turns system audio into live on-screen English.

## Data flow
```
                 ┌──────────────────────── capture thread ───────────────────────┐
                 │                                                                │
 default output  │  AudioCapture.frames()            Segmenter.process(frame)     │
 device (loopback)──▶ read native block ──▶ mono ──▶ resample 16k ──▶ VAD ──┐     │
                 │   (e.g. 48kHz/8ch)                30ms / 480 samples      │     │
                 │                                                          │     │
                 │                          ┌── ("partial", audio) ────────┤     │
                 │                          └── ("final",   audio) ────────┘     │
                 └───────────────────────────────────│──────────────────────────┘
                                                      ▼
                                                  utt_q (Queue)
                                                      │
                 ┌──────────────────── transcribe thread ───────────────────────┐
                 │  drain + COALESCE:                                            │
                 │   • run every "final"                                         │
                 │   • run only the LATEST "partial" (drop stale)               │
                 │            │                                                  │
                 │   Transcriber.translate(audio) → (text, lang, prob)          │
                 │            │                                                  │
                 │   on_result(text, lang, prob, is_partial)                    │
                 └────────────│─────────────────────────────────────────────────┘
                              ▼
                       Bridge.result  (Qt signal, thread-safe)
                              ▼
                 ┌──────────────── Qt main thread ──────────────┐
                 │  OverlayWindow.add_result(...)               │
                 │   • is_partial → dimmed live line (replaced) │
                 │   • final      → committed white line        │
                 │  auto-scroll QTextEdit to newest             │
                 └──────────────────────────────────────────────┘
```

## Threads
- **Capture thread** (`Pipeline._capture_loop`): pulls loopback audio, resamples,
  runs VAD segmentation, pushes events. CPU-light.
- **Transcribe thread** (`Pipeline._transcribe_loop`): the only place that calls
  the GPU model. Single-threaded by design (one model instance).
- **Qt main thread**: UI only. Worker threads reach it exclusively via `Bridge`
  Qt signals (queued connections) — widgets are never touched off-thread.

## Why streaming partials
A naïve design waits for end-of-utterance (silence) before transcribing, so
latency ≈ sentence length + silence wait. Instead the segmenter emits a
`partial` every `partial_interval_ms` (default 700 ms) over the audio-so-far,
which is transcribed and shown dimmed, then replaced/committed by the `final` on
a pause. Perceived latency drops to ~1s.

## Why queue coalescing
Partials are re-transcriptions of a growing buffer; if the GPU falls behind they
could pile up and lag. `_transcribe_loop` drains the queue each iteration and
keeps **only the most recent partial** (plus every final). Live text therefore
always reflects the newest audio instead of a backlog.

## Latency budget (medium, int8_float16, RTX 3060)
| Stage | Cost |
|-------|------|
| partial cadence | ~700 ms |
| inference / pass (after warmup) | ~0.35 s |
| **perceived** | **~1 s behind speaker** |
Model load + warmup (one-time, during "Loading…"): a few seconds.

## Key invariants
- VAD frames are **exactly** 30 ms / 480 samples (webrtcvad requirement);
  `AudioCapture` pads/trims to guarantee this.
- Capture is always **default output device** loopback. If the user's game audio
  is on a non-default device, capture is silent — `test_audio.py` diagnoses this.
- `transcriber._enable_cuda_dlls()` must run before importing/constructing the
  model, or cuBLAS/cuDNN DLLs aren't found.

## Tuning map (config.json → effect)
- Latency snappier: ↓ `vad.partial_interval_ms`, ↓ `vad.silence_ms` (more GPU,
  more sentence fragmentation).
- Accuracy: `model.path` → medium; or ↑ `model.beam_size` (slower).
- Gaming/VRAM headroom: `model.compute_type = int8_float16`, or `model.path` →
  small.
- Fewer false triggers in noise: ↑ `vad.aggressiveness`.
