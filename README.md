# Valorant Voice-Chat Translator

Real-time, on-screen translation of in-game voice chat. Captures your system
audio, detects speech, and uses Whisper to translate it (**any language →
English**) into an always-on-top overlay window — fully **local, offline, and
free** on an NVIDIA GPU.

Built and tuned for an **NVIDIA RTX 3060 Laptop (6 GB)** + Ryzen 5 5600H.

---

## ⚠️ Anti-cheat note (read this first)
This tool stays completely **external** to Valorant and is safe to run alongside
Riot Vanguard:
- Audio is captured at the **OS level** (WASAPI loopback) — it never reads,
  hooks, or injects into the game process.
- Translations show in a **separate** always-on-top window — nothing is drawn
  into the game's render pipeline.

**Do not** add DirectX/overlay injection or game-memory reading. That is exactly
what Vanguard flags. Keep everything external. See [CLAUDE.md](CLAUDE.md).

For the overlay to appear over the game, run Valorant in **Windowed Fullscreen**
(Settings → Video → Display Mode), *not* exclusive fullscreen.

---

## How it works
```
System audio (game + voice chat, default output device)
  → [audio_capture]   WASAPI loopback → 16 kHz mono frames
  → [vad_segmenter]   webrtcvad splits the stream into utterances,
                      emitting live "partial" results while someone talks
  → [transcriber]     faster-whisper "translate" task → English text
                      (auto-detects the source language)
  → [overlay]         auto-scrolling translucent window + tray controls
```

**Latency:** results stream in **live** (~1s behind the speaker). Partial text
appears dimmed while someone is still talking and is committed (solid) once they
pause. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Known limitation:** Valorant mixes voice chat together with game sound through
one output device, so transcription degrades during loud moments (gunfire). This
is inherent to the game — there is no clean per-stream voice feed to capture (yet, or known to me).

---

## Setup

### 1. Dependencies
```powershell
# from D:\unlocked games\customs
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Download a model (manual — see note)
Models are loaded from a **local folder** (not auto-downloaded), because
`huggingface.co` is often blocked for programmatic requests on this machine even
though the browser can reach it.

In your **browser**, open the model page and download all four files into the
matching `models/` folder:

| Model | Page | Folder |
|-------|------|--------|
| small (~460 MB, fast) | https://huggingface.co/Systran/faster-whisper-small/tree/main | `models/faster-whisper-small/` |
| medium (~1.5 GB, accurate) | https://huggingface.co/Systran/faster-whisper-medium/tree/main | `models/faster-whisper-medium/` |

Required files: `model.bin`, `config.json`, `tokenizer.json`, `vocabulary.txt`.

Verify a downloaded model loads on the GPU:
```powershell
.\.venv\Scripts\python.exe verify_model.py models\faster-whisper-medium
```

---

## Run
```powershell
.\.venv\Scripts\python.exe src\main.py                 # normal run
.\.venv\Scripts\python.exe src\main.py --list-devices  # show capture devices
.\.venv\Scripts\python.exe src\main.py --device cpu    # force CPU fallback
.\.venv\Scripts\python.exe test_audio.py               # 6s audio-level meter
```
Control it from the **system-tray icon** (blue 文): pause, toggle overlay/window,
click-through, opacity, clear, quit. In overlay mode, drag the window to
reposition it (unless click-through is on).

---

## Configuration (`config.json`)

### `model`
| Key | Meaning |
|-----|---------|
| `path` | Local model folder (overrides `size`). Switch models by editing this line. |
| `size` | Used only if `path` is null: `tiny`/`base`/`small`/`medium`/`large-v3`. |
| `device` | `auto` (GPU then CPU) / `cuda` / `cpu`. |
| `compute_type` | `int8_float16` (recommended on GPU — ~1.5 GB VRAM, fast), `float16`, `int8`. |
| `task` | `translate` (→ English) or `transcribe` (verbatim, keeps source language). |
| `language` | `null` = auto-detect source language. |
| `beam_size` | `1` = greedy/fastest. |

### `vad`
| Key | Meaning |
|-----|---------|
| `aggressiveness` | `0`–`3`; higher filters more non-speech. |
| `silence_ms` | Trailing silence that finalizes an utterance (lower = snappier). |
| `partial_interval_ms` | How often live partials refresh (lower = snappier, more GPU). |
| `min_speech_ms` | Drops blips shorter than this. |
| `max_utterance_ms` | Force-commits a monologue after this long. |

### `ui`
`mode` (`overlay`/`window`), `opacity`, `font_size`, `width`/`height`, `x`/`y`,
`click_through`, `show_original_lang`.

---

## Switching models (A/B)
Edit one line in `config.json`:
```json
"path": "models/faster-whisper-medium"   // ← or "models/faster-whisper-small"
```
- **medium** — best accuracy; ~0.35s/pass after warmup. Use for real comms.
- **small** — lightest GPU load / max FPS. Use if a match needs every frame.

---

## Project layout
| File | Purpose |
|------|---------|
| `src/main.py` | Entry point; CLI args; wires pipeline ↔ UI. |
| `src/config.py` | Defaults + `config.json` loader. |
| `src/audio_capture.py` | WASAPI loopback → 16 kHz mono frames. |
| `src/vad_segmenter.py` | VAD → `partial`/`final` utterance events. |
| `src/transcriber.py` | faster-whisper wrapper + CUDA DLL setup + warmup. |
| `src/pipeline.py` | Worker threads + queue coalescing. |
| `src/overlay.py` | Auto-scrolling overlay/window + tray. |
| `verify_model.py` | Checks a local model loads + runs. |
| `test_audio.py` | Audio-capture level meter. |
| `models/` | Local model folders (not committed). |

---

## Roadmap ideas
- Pin detected language (skip re-detection per partial) for speed/consistency
- Speaker separation / per-player labelling
- Arbitrary target languages (add an MT step after transcription)
- Global hotkeys; history log export
