# BatGlass

Offline smart glasses software for Raspberry Pi 5. The current stack combines three button-driven features:

- scene description via STT + VLM + TTS
- OCR / text reading via Tesseract with VLM fallback
- proximity-based audio feedback

## Hardware

- Raspberry Pi 5
- Arducam 64MP Hawkeye / IMX519 camera
- Raspberry Pi AI HAT+ 2 with Hailo-10H
- WM8960 Audio HAT
- HC-SR04 ultrasonic sensor

See [docs/hardware.md](docs/hardware.md) for setup notes and device-specific details.

## Entry Points

| Command | Entry Point | Purpose |
|---|---|---|
| `batglass-ocr` | `camera_ocr.cli:main` | OCR camera test CLI |
| `batglass-snap` | `camera_ocr.snap_cli:main` | Single autofocus still capture + OCR/VLM |
| `batglass-beep` | `proximity.__main__:main` | Proximity beep loop |
| `batglass-buttons` | `buttons.__main__:main` | Full three-button runtime |

## Button Mapping

- GPIO `17`: hold to ask a scene question, release to process
- GPIO `27`: tap to read visible text aloud
- GPIO `22`: tap to toggle echolocation beeps

The button stack shares one `Picamera2` instance and one VLM instance across OCR and scene mode. On supported cameras, still captures now run autofocus before capture.

## Quick Start

Create the virtualenv and install the package:

```bash
uv sync
uv pip install -e .
```

Install system packages used by the current runtime:

```bash
sudo apt install -y \
  tesseract-ocr \
  libtesseract-dev \
  python3-picamera2 \
  sox \
  alsa-utils \
  lsof
```

The full button runtime also expects these tools to be present:

- `whisper-cli` on `PATH`
- `piper` in the active environment or `.venv/bin/piper`
- `hailortcli` and HailoRT `5.2.0` for the Hailo VLM path
- `reference/hailo-apps` checked out locally

If Hailo is unavailable, `batglass-buttons` falls back to the CPU VLM runner in `src/batglass/vlm.py`.

## Running

### Full button stack

Packaged entry point:

```bash
batglass-buttons
```

Project-local launcher with the required Hailo environment:

```bash
./run_buttons.sh
```

Equivalent direct invocation:

```bash
PYTHONPATH=src:reference/hailo-apps \
hailort_version=5.2.0 \
.venv/bin/python -m buttons.__main__
```

### OCR camera CLI

```bash
batglass-ocr preview
batglass-ocr capture-once
batglass-ocr capture-interval --interval-ms 1000 --count 5
batglass-ocr ocr-from-file arducam-test.jpg
```

### Snap + OCR / VLM

```bash
batglass-snap
batglass-snap --llm --model moondream
batglass-snap --image captures/snap_2026-02-10_103151.jpg
```

### Proximity only

```bash
batglass-beep
```

## Configuration

`config.yaml` controls OCR mode and some runtime parameters. The current keys are:

```yaml
ocr:
  engine: vlm   # or: tesseract
  vlm_fallback_threshold: 20

scene:
  max_hold_duration_s: 30
  max_tokens: 100

tts:
  model: models/piper/en_US-lessac-medium.onnx
  audio_device: hw:wm8960soundcard

stt:
  model: whisper.cpp/models/ggml-base.en.bin
  audio_device: hw:wm8960soundcard
  threads: 4
```

## Project Layout

```
src/
  batglass/
    hailo_vlm.py    # Hailo-10H Qwen2-VL runner
    stt.py          # whisper.cpp wrapper
    tts.py          # Piper -> aplay wrapper
    vlm.py          # CPU VLM wrapper (llama-mtmd-cli)
    modes/
      ocr.py
      scene.py
  buttons/
    __main__.py     # concurrent GPIO runtime
    beep_button.py
    ocr_button.py
    scene_button.py
  camera_ocr/
    camera.py       # Picamera2 + autofocus capture path
    cli.py          # OCR camera CLI
    snap_cli.py     # rpicam-still capture CLI
  proximity/
    sensor.py
    beep.py
run_buttons.sh      # local launcher with Hailo env
batglass.service    # systemd unit
docs/               # hardware notes and implementation plan
```
