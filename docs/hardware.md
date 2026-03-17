# BatGlass Hardware

## Raspberry Pi 5 — 8 GB

## Camera — Arducam 64MP (Hawkeye / IMX519)
- Connected via camera ribbon
- https://docs.arducam.com/Raspberry-Pi-Camera/Native-camera/64MP-Hawkeye/
- Current sensor: Hawkeye (IMX519)
- Current connection: `dtoverlay=arducam-64mp,cam0`

## AI Accelerator — Raspberry Pi AI HAT+ 2 (Hailo-10H)
- **40 TOPS** (vs 13 TOPS on Hailo-8L)
- Connected via M.2 PCIe — confirmed detected: `0001:01:00.0 Co-processor: Hailo Technologies Ltd. Hailo-10H AI Processor (rev 01)`
- HailoRT driver: **not yet installed** (no `/dev/hailo*`)
- Install: https://hailo.ai/developer-zone/documentation/hailort/
  ```bash
  # Download HailoRT .deb for aarch64 from Hailo developer zone
  sudo dpkg -i hailort_<version>_arm64.deb
  sudo reboot
  # Verify:
  hailortcli scan
  ```
- Once driver is installed, llama.cpp can target it via `GGML_HAILO=ON` cmake flag

### Impact on latency targets
| Feature | CPU-only | With Hailo-10H |
|---------|----------|----------------|
| OCR (Tesseract fast path) | ~500ms ✅ | unchanged (runs on CPU) |
| OCR VLM fallback | ~4–6s ⚠️ | <1s ✅ |
| Scene description (moondream2) | 7–8s ✅ | 1–2s ✅ |

## Audio — WM8960 Audio HAT
- ALSA device: `hw:wm8960soundcard`
- Record mic: `arecord -D hw:wm8960soundcard -f S16_LE -r 16000`
- Play: `aplay -D hw:wm8960soundcard`

## Proximity — HC-SR04
- TRIG: GPIO 23, ECHO: GPIO 24
- Handled by `src/proximity/`