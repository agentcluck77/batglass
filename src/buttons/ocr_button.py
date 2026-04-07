#!/usr/bin/env python3
"""GPIO 27 — OCR button: capture image → OCR → TTS."""

from __future__ import annotations

import time
from pathlib import Path

import contextlib
import cv2
import lgpio
import yaml

_nullcontext = contextlib.nullcontext

from batglass.ocr_engine import TesseractOcrEngine
from batglass.tts import TtsSpeaker
from camera_ocr.camera import Picamera2Source, to_bgr

# -- config -------------------------------------------------------------------
BUTTON_PIN = 27

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TTS_MODEL   = PROJECT_ROOT / "models/piper/en_US-lessac-medium.onnx"
VLM_MODEL   = PROJECT_ROOT / "models/moondream2/moondream2-text-model-f16_ct-vicuna.gguf"
VLM_MMPROJ  = PROJECT_ROOT / "models/moondream2/moondream2-mmproj-f16-20250414.gguf"

def _load_config() -> dict:
    cfg_path = PROJECT_ROOT / "config.yaml"
    if cfg_path.exists():
        with open(cfg_path) as f:
            return yaml.safe_load(f) or {}
    return {}
# -----------------------------------------------------------------------------

OCR_PROMPT = "Transcribe all text visible in this image. Only output the text, nothing else."


class OcrButton:
    def __init__(self, chip: int = 0, camera=None, camera_lock=None, vlm=None) -> None:
        cfg = _load_config()
        ocr_cfg = cfg.get("ocr", {})
        self._ocr_engine = ocr_cfg.get("engine", "tesseract")
        self._vlm_min_confidence = ocr_cfg.get("vlm_fallback_threshold", 20)

        self._ocr = TesseractOcrEngine()
        self._tts = TtsSpeaker(model=TTS_MODEL)
        self._vlm = vlm
        print(f"[ocr_button] engine={self._ocr_engine} vlm={type(vlm).__name__ if vlm else 'none'}")
        self._camera = camera or Picamera2Source(width=1280, height=720)
        self._camera_lock = camera_lock
        self._owns_camera = camera is None
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_input(self._chip, BUTTON_PIN, lgpio.SET_PULL_UP)

    def run(self) -> None:
        """Poll for button presses and run OCR on each press."""
        print(f"[ocr_button] listening on GPIO {BUTTON_PIN} — press to read text")
        if self._owns_camera:
            self._camera.start()
        try:
            while True:
                if _button_pressed(self._chip, BUTTON_PIN):
                    print(f"[GPIO {BUTTON_PIN}] OCR — read text aloud")
                    self._handle()
        finally:
            if self._owns_camera:
                self._camera.stop()
            lgpio.gpiochip_close(self._chip)

    def _handle(self) -> None:
        t0 = time.perf_counter()
        with self._camera_lock if self._camera_lock else _nullcontext():
            frame = self._camera.capture_frame()
        t_cap = time.perf_counter()
        frame_bgr = to_bgr(frame, input_is_rgb=getattr(self._camera, "output_is_rgb", False))

        if self._ocr_engine == "vlm":
            # Skip Tesseract entirely
            print(f"[ocr_button] VLM mode capture={1000*(t_cap-t0):.0f}ms")
            if self._vlm is None:
                self._tts.speak("VLM not available.")
                return
            img_path = Path("/tmp/batglass_ocr_btn.jpg")
            cv2.imwrite(str(img_path), frame_bgr)
            print("[ocr_button] running VLM inference...")
            tokens = self._vlm.run(image_path=img_path, prompt=OCR_PROMPT, max_tokens=150)
            print("[ocr_button] streaming TTS")
            self._tts.speak_stream(_tee_tokens(tokens, "[ocr_button] text:"))
            print("[ocr_button] done")
            return

        # Tesseract path
        result = self._ocr.run(frame_bgr)
        t_ocr = time.perf_counter()
        print(
            f"[ocr_button] conf={result.confidence:.1f} "
            f"capture={1000*(t_cap-t0):.0f}ms "
            f"ocr={1000*(t_ocr-t_cap):.0f}ms"
        )

        if result.text and result.confidence >= TesseractOcrEngine.CONFIDENCE_THRESHOLD:
            self._tts.speak(result.text)
            return

        if self._vlm is None or result.confidence < self._vlm_min_confidence:
            self._tts.speak(result.text if result.text else "No text found.")
            return

        print(f"[ocr_button] low confidence ({result.confidence:.1f}), falling back to VLM")
        img_path = Path("/tmp/batglass_ocr_btn.jpg")
        cv2.imwrite(str(img_path), frame_bgr)
        tokens = self._vlm.run(image_path=img_path, prompt=OCR_PROMPT, max_tokens=150)
        self._tts.speak_stream(_tee_tokens(tokens, "[ocr_button] text:"))


def _tee_tokens(tokens, label: str):
    """Yield tokens unchanged while printing them to stdout for debugging."""
    buf = []
    for tok in tokens:
        buf.append(tok)
        yield tok
    print(f"{label} {''.join(buf)!r}")


def _button_pressed(chip: int, pin: int, debounce: float = 0.05) -> bool:
    """Return True once per press (active-low, waits for release)."""
    if lgpio.gpio_read(chip, pin) != 0:
        time.sleep(0.01)  # idle sleep to avoid busy-loop
        return False
    time.sleep(debounce)
    if lgpio.gpio_read(chip, pin) != 0:
        return False
    # wait for release
    while lgpio.gpio_read(chip, pin) == 0:
        time.sleep(0.01)
    return True


if __name__ == "__main__":
    OcrButton().run()
