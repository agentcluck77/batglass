# BatGlass

Smart glasses firmware for Raspberry Pi — modular monorepo combining proximity-based audio feedback and OCR/VLM image capture.

## Modules

| Module | Entry Point | Description |
|---|---|---|
| `camera_ocr` | `batglass-ocr` | OCR camera CLI (Picamera2 + Tesseract) |
| `camera_ocr.snap_cli` | `batglass-snap` | Snap a photo and run OCR or VLM |
| `proximity` | `batglass-beep` | HC-SR04 ultrasonic sensor + WM8960 beeper |

## Hardware

- Arducam 64MP (IMX519 / Hawkeye) — camera ribbon to Pi
- HC-SR04 — ultrasonic sensor on GPIO 23 (TRIG) / 24 (ECHO)
- WM8960 Audio HAT — driver in `hardware/WM8960-Audio-HAT/`

See `docs/hardware.md` for full setup.

## Quick Start

```bash
uv sync
uv pip install -e .
sudo apt install -y tesseract-ocr libtesseract-dev python3-picamera2
```

For Ollama/VLM support:
```bash
uv pip install -e ".[vlm]"
```

## Usage

### OCR camera (live / interval)

```bash
# Live preview (requires graphical session)
batglass-ocr preview

# Capture once and OCR
batglass-ocr capture-once

# Capture every 1s for 5 frames
batglass-ocr capture-interval --interval-ms 1000 --count 5

# OCR from an existing image file
batglass-ocr ocr-from-file arducam-test.jpg
```

### Snap + OCR

```bash
# Snap with autofocus and run Tesseract OCR
batglass-snap

# Use a vision LLM (Ollama) instead
batglass-snap --llm --model moondream

# OCR an existing image
batglass-snap --image captures/snap_2026-02-10_103151.jpg
```

### Proximity beep

```bash
# Start the proximity beep loop (Ctrl+C to stop)
batglass-beep
```

Or run the module directly:
```bash
uv run python -m proximity
```

## Project Layout

```
src/
  camera_ocr/
    camera.py       # Picamera2 + image file input
    ocr.py          # Tesseract OCR pipeline
    snap_cli.py     # Snap CLI (rpicam-still + OCR/VLM)
    vlm.py          # Optional Ollama VLM backend
    cli.py          # OCR camera CLI
  proximity/
    sensor.py       # HC-SR04 distance measurement
    beep.py         # WM8960 audio beep output
    __main__.py     # Proximity beep loop
scripts/
  ocr_camera.py     # Shim → batglass-ocr
  snap_ocr.py       # Shim → batglass-snap
hardware/
  WM8960-Audio-HAT/ # Audio HAT driver (submodule)
captures/           # Saved snapshots (gitignored)
photos/             # OCR artifacts (gitignored)
docs/               # Setup and hardware docs
```

## System Dependencies

```bash
sudo apt install -y \
  tesseract-ocr \
  libtesseract-dev \
  python3-picamera2 \
  sox \
  alsa-utils
```
