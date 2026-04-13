#!/usr/bin/env python3
"""GPIO 27 — OCR button: capture image → Gemini Live OCR → audio output."""

from __future__ import annotations

import time
from pathlib import Path

import contextlib
import lgpio
import yaml

_nullcontext = contextlib.nullcontext

from buttons.artifacts import save_button_frame
from camera_ocr.camera import Picamera2Source, to_bgr

# -- config -------------------------------------------------------------------
BUTTON_PIN = 27

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def _load_config() -> dict:
    cfg_path = PROJECT_ROOT / "config.yaml"
    if cfg_path.exists():
        with open(cfg_path) as f:
            return yaml.safe_load(f) or {}
    return {}
# -----------------------------------------------------------------------------

OCR_PROMPT = (
    "Read the text in this image aloud exactly as written. "
    "Do not add any explanations, labels, or commentary. "
    "If there is no readable text in the image, say: No text found."
)


class OcrButton:
    def __init__(self, chip: int = 0, camera=None, camera_lock=None, live=None) -> None:
        self._live = live
        print(f"[ocr_button] backend={type(live).__name__ if live else 'none'}")
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
        try:
            with self._camera_lock if self._camera_lock else _nullcontext():
                frame = self._camera.capture_frame()
        except Exception as exc:
            print(f"[ocr_button] capture failed: {exc}")
            return
        t_cap = time.perf_counter()
        print(f"[ocr_button] capture={1000*(t_cap-t0):.0f}ms")
        frame_bgr = to_bgr(frame, input_is_rgb=getattr(self._camera, "output_is_rgb", False))

        t_save0 = time.perf_counter()
        try:
            image_path = save_button_frame(frame_bgr, "ocr", "button_ocr")
        except Exception as exc:
            print(f"[ocr_button] failed to save frame: {exc}")
            image_path = frame_bgr
        print(f"[ocr_button] save={1000*(time.perf_counter()-t_save0):.0f}ms")

        if self._live is None:
            print("[ocr_button] no live runner configured")
            return

        t_live0 = time.perf_counter()
        try:
            self._live.speak_image(image_path, OCR_PROMPT)
        except Exception as exc:
            print(f"[ocr_button] live request failed: {exc}")
        print(f"[ocr_button] live={1000*(time.perf_counter()-t_live0):.0f}ms  total={1000*(time.perf_counter()-t0):.0f}ms")


def _button_pressed(chip: int, pin: int, debounce: float = 0.05) -> bool:
    if lgpio.gpio_read(chip, pin) != 0:
        time.sleep(0.01)
        return False
    time.sleep(debounce)
    if lgpio.gpio_read(chip, pin) != 0:
        return False
    while lgpio.gpio_read(chip, pin) == 0:
        time.sleep(0.01)
    return True


if __name__ == "__main__":
    OcrButton().run()
