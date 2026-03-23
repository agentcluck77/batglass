# BatGlass — Implementation Plan

## Product overview

Smart glasses running fully offline on Raspberry Pi 5. Two user-facing features:

| Feature | Trigger | Pipeline | Latency target |
|---------|---------|----------|----------------|
| **Scene description** | Hold button A → speak question → release | STT + VLM + TTS | 5–10 s |
| **OCR / read** | Tap button B | Camera → RapidOCR (→ VLM fallback) → TTS | 1–2 s |

Hardware already working: Arducam 64MP, WM8960 Audio HAT, HC-SR04 proximity sensor, Pi 5 8 GB.

---

## Environment & tooling reference

> For future agents: this is what is installed, where things live, and how to run them.

### Shell PATH (set in `~/.bashrc`)

```bash
export PATH="$HOME/batglass/llama.cpp/build/bin:$PATH"
export PATH="$HOME/batglass/whisper.cpp/build/bin:$PATH"
```

After sourcing, the following binaries are available directly:
- `llama-mtmd-cli` — multimodal VLM inference
- `llama-cli`, `llama-bench`, etc. — other llama.cpp tools
- `whisper-cli` — speech-to-text

### Python environment

- Package manager: `uv` (not pip/conda)
- Run commands: `uv run <cmd>` or activate `.venv`
- Install packages: `uv add <package>`
- `picamera2` is a system package — `.venv/pyvenv.cfg` has `include-system-site-packages = true`

### Key binaries & models

| Tool | Binary | Notes |
|------|--------|-------|
| VLM | `llama-mtmd-cli` | built at `llama.cpp/build/bin/`, on PATH |
| STT | `whisper-cli` | built at `whisper.cpp/build/bin/`, on PATH |
| TTS | `uv run piper` | Python package, voice model at `models/piper/` |
| Camera | `rpicam-still` | system binary, Arducam 64MP tuning file auto-loaded |
| HF download | `hf` (brew) | `hf download <repo> <file> --local-dir <dir>` |

### Model paths

| Model | Path | Command |
|-------|------|---------|
| moondream2 text (f16) | `models/moondream2/moondream2-text-model-f16_ct-vicuna.gguf` | VLM language model |
| moondream2 mmproj | `models/moondream2/moondream2-mmproj-f16-20250414.gguf` | VLM vision encoder |
| whisper base.en | `whisper.cpp/models/ggml-base.en.bin` | STT model |
| Piper voice | `models/piper/en_US-lessac-medium.onnx` | TTS voice |

### Verified working commands

```bash
# VLM — describe image
llama-mtmd-cli \
  -m models/moondream2/moondream2-text-model-f16_ct-vicuna.gguf \
  --mmproj models/moondream2/moondream2-mmproj-f16-20250414.gguf \
  --chat-template vicuna --image /tmp/test.jpg \
  -p "Describe this image." -t 4 --temp 0.1 -n 80 2>/dev/null

# TTS — synthesise to WAV
echo "Hello." | uv run piper \
  --model models/piper/en_US-lessac-medium.onnx \
  --output-file /tmp/out.wav

# TTS — stream raw audio to speaker
echo "Hello." | uv run piper \
  --model models/piper/en_US-lessac-medium.onnx \
  --output-raw | aplay -r 22050 -f S16_LE -t raw -

# STT — transcribe WAV
whisper-cli -m whisper.cpp/models/ggml-base.en.bin \
  -f /tmp/test.wav -t 4 --no-timestamps 2>/dev/null

# Camera — capture still with autofocus
rpicam-still -t 3000 --width 1280 --height 720 --autofocus-mode auto -o /tmp/test.jpg
```

### Audio device

- WM8960 Audio HAT is the audio interface
- ALSA device name: `hw:wm8960soundcard` (record and playback)
- Record: `arecord -D hw:wm8960soundcard -f S16_LE -r 16000`
- Play WAV: `aplay -D hw:wm8960soundcard /tmp/out.wav`
- Play raw: `aplay -D hw:wm8960soundcard -r 22050 -f S16_LE -t raw -`

---

## Current state

| Component | Status |
|-----------|--------|
| Camera (Picamera2 + Arducam 64MP) | ✅ Working |
| Tesseract OCR pipeline (`src/camera_ocr/`) | ✅ Working |
| llama.cpp built (`llama-mtmd-cli`, `llama-llava-cli`) | ✅ Built |
| WM8960 Audio HAT driver | ✅ Installed |
| Proximity sensor (`src/proximity/`) | ✅ Working |
| moondream2 GGUF downloaded | ✅ `models/moondream2/` (f16, 2.7 GB text + 868 MB mmproj) |
| whisper.cpp built | ✅ `whisper.cpp/build/bin/whisper-cli`, model at `whisper.cpp/models/ggml-base.en.bin` |
| Piper TTS installed | ✅ `piper-tts` via uv, voice at `models/piper/en_US-lessac-medium.onnx` |
| Hailo-10H AI HAT+ 2 | ✅ Working with HailoRT 5.2.0 and `Qwen2-VL-2B-Instruct`; manual Hailo install still required |
| `src/batglass/tts.py` (TtsSpeaker) | ✅ Phase 1 complete |
| `src/batglass/ocr_engine.py` + `modes/ocr.py` | ✅ Phase 2 complete |
| `src/batglass/vlm.py` (VlmRunner) | ✅ Phase 3 complete — stdout capture, working |
| `src/batglass/stt.py` (SttRunner) | ✅ Phase 4 complete |
| `src/batglass/modes/scene.py` (SceneMode) | ✅ Phase 5 complete |
| Button GPIO + dispatcher (`src/buttons/`) | ✅ Phase 6 complete — STT wired into scene_button |
| `batglass.service` systemd unit | ✅ Phase 7 complete |
| Hardening (thermal, config, error TTS) | ❌ Phase 8 pending |

---

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │           BatGlass Daemon            │
                    │                                      │
  Button A (hold) ──┤─► ButtonListener                    │
  Button B (tap)  ──┤        │                            │
                    │        ▼                            │
                    │   ModeDispatcher                    │
                    │    ├── SceneMode ──────────────────►│
                    │    └── OcrMode  ──────────────────►│
                    │                                      │
                    │  SceneMode:                         │
                    │    AudioRecorder → Whisper STT ─┐   │
                    │    Camera.capture() ────────────┤   │
                    │                                 ▼   │
                    │                         VlmRunner   │
                    │                    (llama-mtmd-cli) │
                    │                              │      │
                    │  OcrMode:                    │      │
                    │    Camera.capture()           │      │
                    │    RapidOcrEngine ─┐          │      │
                    │    (conf < 0.75)   │          │      │
                    │    VlmRunner ◄─────┘          │      │
                    │                               │      │
                    │                               ▼      │
                    │                        TtsSpeaker    │
                    │                    (piper → aplay)   │
                    └─────────────────────────────────────┘
```

### Source layout (target)

```
src/
  batglass/
    __main__.py         # daemon entry point
    dispatcher.py       # ModeDispatcher + ButtonListener
    modes/
      scene.py          # SceneMode orchestration
      ocr.py            # OcrMode orchestration
    camera.py           # thin wrapper (reuses camera_ocr.camera)
    vlm.py              # VlmRunner — subprocess wrapper for llama-mtmd-cli
    stt.py              # SttRunner — subprocess wrapper for whisper.cpp
    tts.py              # TtsSpeaker — streaming piper → aplay
    ocr_engine.py       # RapidOcrEngine + Tesseract fallback
  camera_ocr/           # existing, kept as-is
  proximity/            # existing, kept as-is
```

---

## Phases

### Phase 0 — Model + TTS setup (no code changes)

**Goal:** get the inference stack runnable end-to-end from the command line.

1. ✅ **Download moondream2 GGUF** — `models/moondream2/` (f16 vicuna, 2.7 GB + 868 MB mmproj)
   ```bash
   hf download ggml-org/moondream2-20250414-GGUF \
     moondream2-text-model-f16_ct-vicuna.gguf \
     moondream2-mmproj-f16-20250414.gguf \
     --local-dir models/moondream2
   ```

2. ✅ **Install Piper TTS** — `piper-tts` via `uv add`, voice at `models/piper/en_US-lessac-medium.onnx`
   ```bash
   uv add piper-tts pathvalidate
   wget -P models/piper \
     "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
     "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
   ```

3. ❌ **Build whisper.cpp** — next step
   ```bash
   git clone https://github.com/ggerganov/whisper.cpp
   cd whisper.cpp
   cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DGGML_NEON=ON -DGGML_OPENMP=ON
   cmake --build build -j4
   ./build/bin/whisper-cli --download-model base.en
   ```

4. ✅ **VLM smoke test** — verified moondream2 describes a captured image correctly
   ```bash
   # Working command (--no-display-prompt not supported, omit it)
   llama-mtmd-cli \
     -m models/moondream2/moondream2-text-model-f16_ct-vicuna.gguf \
     --mmproj models/moondream2/moondream2-mmproj-f16-20250414.gguf \
     --chat-template vicuna --image /tmp/test.jpg \
     -p "Describe this image." -t 4 --temp 0.1 -n 80 2>/dev/null
   ```

5. ✅ **Piper smoke test** — verified WAV output
   ```bash
   echo "Hello." | uv run piper \
     --model models/piper/en_US-lessac-medium.onnx \
     --output-file /tmp/test.wav
   ```

6. ✅ **STT smoke test** — verified on JFK sample ("ask not what your country can do for you...")
   ```bash
   arecord -D hw:wm8960soundcard -f S16_LE -r 16000 -d 5 /tmp/test.wav
   whisper.cpp/build/bin/whisper-cli \
     -m whisper.cpp/models/ggml-base.en.bin \
     -f /tmp/test.wav -t 4 --no-timestamps
   ```

**Exit criteria:** VLM ✅ describes a photo. Piper ✅ synthesises WAV. STT ✅ transcribes audio. Phase 0 complete.

---

### Phase 1 — TTS module (`src/batglass/tts.py`)

**Goal:** reusable Python wrapper that streams Piper output to the speaker.

- `TtsSpeaker.speak(text: str)` — blocking, plays full text
- `TtsSpeaker.speak_stream(token_iter)` — buffers VLM tokens at sentence boundaries (`.`, `!`, `?`), pipes each sentence to Piper as it arrives; first audio starts after ~10–15 tokens
- Subprocess: `piper --model ... --output-raw | aplay -r 22050 -f S16_LE -t raw -`
- Audio device: `hw:wm8960soundcard`

**Test:** `python -m batglass.tts "Hello, I can see a table."` plays audio.

---

### Phase 2 — OCR feature (`src/batglass/modes/ocr.py`)

**Goal:** button tap → read text aloud in ≤2s.

1. **`src/batglass/ocr_engine.py`** — Tesseract 5 LSTM as primary engine
   - `TesseractOcrEngine.run(frame) → OcrResult` with mean word confidence (0–100)
   - Confidence threshold: 60/100 → escalate to VLM if below
   - Preprocessing: grayscale + adaptive threshold
   - **RapidOCR was benchmarked at ~4s on Pi 5 (CRNN bottleneck) vs Tesseract ~500ms — Tesseract wins**

2. **`src/batglass/modes/ocr.py`** — `OcrMode.run()`
   ```
   capture frame
     → TesseractOcrEngine (~500ms)
       ├── confidence ≥ 60 → TtsSpeaker.speak(text)
       └── confidence < 60 → VlmRunner("Transcribe all text.") → TtsSpeaker.speak_stream()
   ```

3. ✅ `rapidocr-onnxruntime` added to `pyproject.toml` (kept as optional future path)

**Test:** point camera at printed page, call `OcrMode.run()`, hear the text.

---

### Phase 3 — VLM module (`src/batglass/vlm.py`)

**Goal:** reusable wrapper around `llama-mtmd-cli` that streams tokens.

- `VlmRunner(model_path, mmproj_path, threads=4)`
- `VlmRunner.run(image_path, prompt, max_tokens=100) → Iterator[str]` — yields tokens via stdout
- Model stays loaded between calls (persistent subprocess in interactive mode) to avoid reload cost
- Warm-up: one dummy inference at construction to page in mmap regions (~3s, paid once at boot)
- Use `--chat-template vicuna` for moondream2, `--no-display-prompt` to suppress echo

---

### Phase 4 — STT module (`src/batglass/stt.py`)

**Goal:** transcribe recorded audio with whisper.cpp.

- `SttRunner(model_path, threads=4)`
- `SttRunner.transcribe(wav_path: str) → str`
- Subprocess: `whisper-cli -f <wav> -t 4 --no-timestamps --output-txt`
- Model: `ggml-base.en.bin` (~142 MB, ~2.5s for a 5s clip on Pi 5)

---

### Phase 5 — Scene description feature (`src/batglass/modes/scene.py`)

**Goal:** hold button → ask question → release → hear answer in 5–10s.

```
button held     → AudioRecorder.start()
                → Camera.capture() starts in parallel thread
button released → AudioRecorder.stop() → /tmp/question.wav
                → SttRunner.transcribe() → question_text
                  (camera frame already ready — captured in parallel)
                → VlmRunner.run(image_path, question_text) → token stream
                → TtsSpeaker.speak_stream(token_stream)
```

- `AudioRecorder`: `arecord -D hw:wm8960soundcard -f S16_LE -r 16000`, streams to WAV while held, 10s cap
- Camera thread starts at button-press, completes in ~200ms — always done before STT finishes
- TTS overlaps VLM decode — first sentence spoken while VLM generates the second

---

### Phase 6 — Button input + dispatcher (`src/batglass/dispatcher.py`)

**Goal:** physical buttons trigger the right mode.

- **Button A** (scene): hold-to-record, release-to-process — GPIO pin TBD
- **Button B** (OCR): momentary tap — GPIO pin TBD
- `ButtonListener` runs in background thread, pushes events to `queue.Queue`
- `ModeDispatcher` consumes queue, runs the appropriate mode
- Debounce: 50ms
- `gpiozero` for GPIO (already on Pi OS); keyboard fallback for dev (`a` = scene, `b` = OCR)

---

### Phase 7 — Daemon + startup (`src/batglass/__main__.py`)

**Goal:** single process, all models loaded once, survives reboots.

```python
# Startup sequence (all models loaded once, kept resident)
cam = Camera(width=1280, height=720)   # start + 1s warmup
vlm = VlmRunner(...)                   # load + dummy inference (~3s)
stt = SttRunner(...)                   # ready
tts = TtsSpeaker(...)                  # ready
ocr = RapidOcrEngine()                 # load ONNX (~0.5s)

tts.speak("Ready.")

ModeDispatcher(vlm, stt, tts, ocr, cam).run()  # blocks
```

- `systemd` unit: `batglass.service` — start on boot, restart on crash
- Logs to `journald`
- Total RAM at steady state: ~2.7 GB (well within 8 GB)

---

### Phase 8 — Hardening

- Thermal guard: poll `/sys/class/thermal/thermal_zone0/temp`, speak warning if >75°C
- Swap guard: assert swap off at startup
- Audio error feedback: speak "Camera error" / "No text found" / "Too hot, slowing down"
- `batglass.toml` config: model paths, GPIO pins, confidence threshold, max tokens, audio device
- Graceful shutdown on SIGTERM

---

## Dependency summary

### Python (`pyproject.toml`)

```toml
dependencies = [
  "opencv-python>=4.8",
  "pytesseract>=0.3",        # kept as OCR fallback
  "pillow>=10.0",
  "numpy>=1.24",
  "rapidocr-onnxruntime",    # Phase 2 — primary OCR engine
  "gpiozero",                # Phase 6 — button input
  "RPi.GPIO",                # Phase 6 — GPIO backend
]
```

### System (`apt`)

```bash
sudo apt install -y \
  tesseract-ocr libtesseract-dev \
  python3-picamera2 \
  sox alsa-utils
```

### Binaries (built from source)

| Binary | Location | Status |
|--------|----------|--------|
| `llama-mtmd-cli` | `llama.cpp/build/bin/` | ✅ Built |
| `whisper-cli` | `whisper.cpp/build/bin/` | ❌ Phase 0 |

### Models

| Model | Path | Size | Phase |
|-------|------|------|-------|
| moondream2 text (f16 or Q4_K_M) | `models/moondream2/` | ~1.5 GB | Phase 0 |
| moondream2 mmproj f16 | `models/moondream2/` | ~400 MB | Phase 0 |
| whisper base.en | `whisper.cpp/models/` | ~142 MB | Phase 0 |
| Piper en_US-lessac-medium | `models/piper/` | ~63 MB | Phase 0 |
| RapidOCR ONNX models | auto-downloaded by lib | ~20 MB | Phase 2 |

---

## Latency targets vs expected actuals

### Scene description

| Stage | Expected |
|-------|----------|
| STT (base.en, 5s clip) | 2.5s |
| Camera capture (parallel with STT) | 0.2s |
| VLM TTFT (moondream2) | 0.5–1.0s |
| VLM decode, 80 tokens @ 15 t/s | 5–6s |
| TTS first sentence (overlaps decode) | −0.8s |
| **Total** | **~7–8s** ✅ |

### OCR

| Stage | Expected |
|-------|----------|
| Camera capture | 0.15s |
| RapidOCR fast path | 0.3–0.4s |
| TTS first word | 0.2s |
| **Total (fast path)** | **~0.7s** ✅ |
| VLM fallback total | **~2–3s** ⚠️ |

---

## Hardware upgrade path

**Raspberry Pi AI HAT+ 2 (Hailo-10H, 40 TOPS) is already installed.**
PCIe device detected. Pending: HailoRT driver install + llama.cpp rebuild with `GGML_HAILO=ON`.
See `docs/hardware.md` for driver install instructions.

| Upgrade | Status | Unlocks |
|---------|--------|---------|
> ⚠️ **llama.cpp has no Hailo backend.** Hailo uses compiled `.hef` model files via HailoRT API — not GGUF.
> Prototype remains CPU + llama.cpp. Hailo is a separate future inference path.

| Upgrade | Status | Unlocks |
|---------|--------|---------|
| HailoRT driver install (`apt install hailo-all`) | ❌ install now | Activates `/dev/hailo0`, enables future HailoRT work |
| HailoRT Python API + `.hef` VLM model | ❌ future | <1s VLM via Hailo Model Zoo (LLaMA-3.2 .hef) |
| Swap moondream2 → InternVL2-2B Q4_K_M | ❌ future | Better CPU scene description quality |
| Hands-free activation | ❌ future | ReSpeaker HAT + wake-word |
