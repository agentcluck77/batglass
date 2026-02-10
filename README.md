# BatGlass OCR Camera CLI

A modular command-line tool to test OCR on your camera feed (Picamera2) or image files using Tesseract.

## What It Does
- Live camera preview.
- Capture one frame and run OCR.
- Capture frames on an interval and run OCR repeatedly.
- Run OCR on an existing image file.
- Print plain text output with:
  - average confidence
  - bounding boxes
  - timing metrics
- Save artifacts to `photos/`:
  - captured frame (`.jpg`)
  - annotated OCR frame (`_annotated.jpg`)
  - OCR metadata (`.json`)

## Project Layout
- `src/camera_ocr/cli.py`: CLI layer.
- `src/camera_ocr/camera.py`: camera and image input layer.
- `src/camera_ocr/ocr.py`: OCR + preprocessing layer.
- `scripts/ocr_camera.py`: launcher script.

## Requirements
- Python 3.11+
- Python deps from `pyproject.toml` (`opencv-python`, `pytesseract`, `numpy`, `pillow`)
- System deps:
  - `tesseract-ocr`
  - `libtesseract-dev`
  - `python3-picamera2` (for camera commands)

## Quick Start
```bash
uv sync
sudo apt install -y tesseract-ocr libtesseract-dev python3-picamera2
```

```bash
./.venv/bin/python scripts/ocr_camera.py --help
```

## Usage Examples
```bash
# Preview camera (press q or Esc to quit)
# Requires a graphical session (X/Wayland).
uv run scripts/ocr_camera.py preview

# Capture once and OCR
uv run scripts/ocr_camera.py capture-once

# Capture every 1s, 5 frames
uv run scripts/ocr_camera.py capture-interval --interval-ms 1000 --count 5

# Capture indefinitely without saving files (stop with Ctrl+C)
uv run scripts/ocr_camera.py capture-interval --interval-ms 1000 --no-save

# OCR from file
uv run scripts/ocr_camera.py ocr-from-file arducam-test.jpg
```

## Optional Module Entry
If you run directly from `src`:
```bash
PYTHONPATH=src ./.venv/bin/python -m camera_ocr --help
```
