# BatGlass

Smart glasses software for Raspberry Pi 5. The current button runtime combines three features:

- scene description via Gemini + TTS
- OCR / text reading via Gemini
- proximity-based audio feedback

## Hardware

- Raspberry Pi 5
- Arducam 64MP Hawkeye / IMX519 camera
- Raspberry Pi AI HAT+ 2 with Hailo-10H
- WM8960 Audio HAT
- 2x HC-SR04 ultrasonic sensors

See [docs/hardware.md](docs/hardware.md) for setup notes and device-specific details.

## Entry Points

| Command | Entry Point | Purpose |
|---|---|---|
| `batglass-ocr` | `camera_ocr.cli:main` | OCR camera test CLI |
| `batglass-snap` | `camera_ocr.snap_cli:main` | Single autofocus still capture + OCR/VLM |
| `batglass-beep` | `proximity.__main__:main` | Dual-sensor proximity beeps |
| `batglass-buttons` | `buttons.__main__:main` | Full button runtime |

## Button Mapping

- GPIO `17`: tap to describe the current scene
- GPIO `27`: tap to read visible text aloud
- GPIO `22`: tap to toggle echolocation beeps

The button stack shares one `Picamera2` instance and one Gemini client across OCR and scene mode.

## Quick Start

Create the virtualenv and install the package:

```bash
uv sync
uv pip install -e .
```

Install system packages used by the current runtime:

```bash
sudo apt install -y \
  python3-picamera2 \
  sox \
  alsa-utils \
  lsof
```

The full button runtime also expects these tools to be present:

- `piper` in the active environment or `.venv/bin/piper`
- `GEMINI_API_KEY` in the environment or a project `.env` file

Local OCR and local VLM code paths still exist in the repo for older utilities, but `batglass-buttons` no longer wires them into the active runtime.
If you still use the older camera OCR utilities, install their local dependencies separately, including `tesseract-ocr`.

## Running

### Full button stack

Packaged entry point:

```bash
batglass-buttons
```

Project-local launcher:

```bash
./run_buttons.sh
```

Systemd service for boot-time startup as `aloysius`:

```bash
sudo cp /home/aloysius/batglass/batglass.service /etc/systemd/system/batglass.service
sudo systemctl daemon-reload
sudo systemctl enable --now batglass.service
```

Equivalent direct invocation:

```bash
PYTHONPATH=src \
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
batglass-beep --probe --samples 5
```

## Configuration

`config.yaml` controls Gemini and audio runtime parameters for the button stack. The current keys are:

```yaml
gemini:
  model: gemini-3.1-flash-lite-preview

ocr:
  max_tokens: 160

scene:
  max_tokens: 60

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
    gemini_vlm.py   # Gemini cloud vision runner for buttons
    hailo_vlm.py    # older Hailo VLM path, no longer wired into buttons
    stt.py          # whisper.cpp wrapper
    tts.py          # Piper -> aplay wrapper
    vlm.py          # older CPU VLM wrapper (llama-mtmd-cli)
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
    sensor.py       # HC-SR04 driver
    beep.py         # persistent stereo aplay beeper
    controller.py   # dual-sensor left/right scheduler
run_buttons.sh      # local launcher for the button runtime
batglass.service    # systemd unit
docs/               # hardware notes and implementation plan
```
