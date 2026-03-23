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
- HailoRT driver: **working** with manually installed HailoRT `5.2.0`
- Pi OS Trixie repo still carries older HailoRT packages for Hailo-8/8L, so the 10H path requires manual install from Hailo's developer downloads
- Installed local artifacts are kept under `hardware/hailo/`:
  - `hailort-pcie-driver_5.2.0_all.deb`
  - `hailort_5.2.0_arm64.deb`
  - `hailort-5.2.0-cp313-cp313-linux_aarch64.whl`
- Verified command:
  ```bash
  hailortcli fw-control identify
  ```
  Expected/observed device:
  - `Device Architecture: HAILO10H`
- Inference uses the **HailoRT Python API** via `hailo_platform.genai.VLM` — NOT via llama.cpp
- llama.cpp has no Hailo backend — it uses GGUF, Hailo uses compiled `.hef` files
- Current VLM path:
  - Model: `Qwen2-VL-2B-Instruct`
  - Wrapper: `src/batglass/hailo_vlm.py`
  - Support repo: `reference/hailo-apps`
  - Runtime env: `hailort_version=5.2.0 PYTHONPATH=src:reference/hailo-apps`
- Verified behavior:
  - Hailo VLM loads successfully on-device
  - OCR prompt can read text from a focused 1280x720 camera capture
  - Observed inference time is roughly `3-8s` depending on prompt and warm state

### Impact on latency targets
| Feature | CPU-only (current) | With Hailo-10H (.hef path) |
|---------|----------|----------------|
| OCR (Tesseract fast path) | ~500ms ✅ | unchanged (Tesseract runs on CPU) |
| VLM via llama.cpp (GGUF) | 7–8s ✅ | unchanged — llama.cpp doesn't use Hailo |
| VLM via HailoRT (.hef) | N/A | ~3–8s working now via `Qwen2-VL-2B-Instruct` |

> CPU moondream remains the fallback path.
> Hailo Qwen2-VL is now the primary hardware-accelerated VLM path when available.

## Audio — WM8960 Audio HAT
- ALSA device: `hw:wm8960soundcard`
- Record mic: `arecord -D hw:wm8960soundcard -f S16_LE -r 16000`
- Play: `aplay -D hw:wm8960soundcard`

## Proximity — HC-SR04
- TRIG: GPIO 23, ECHO: GPIO 24
- Handled by `src/proximity/`
