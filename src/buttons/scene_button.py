#!/usr/bin/env python3
"""GPIO 17 — Scene button: press to describe surroundings for a blind person."""

from __future__ import annotations

import time
from pathlib import Path

import contextlib
import cv2
import lgpio

_nullcontext = contextlib.nullcontext

from batglass.tts import TtsSpeaker
from camera_ocr.camera import Picamera2Source, to_bgr

# -- config -------------------------------------------------------------------
BUTTON_PIN = 17

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TTS_MODEL    = PROJECT_ROOT / "models/piper/en_US-lessac-medium.onnx"
# -----------------------------------------------------------------------------

SCENE_PROMPT = (
    "You are assisting a blind person. Describe this scene in two sentences or fewer. "
    "Focus first on any immediate dangers or obstacles such as steps, kerbs, traffic, "
    "wet floors, or moving objects. Then briefly describe the surroundings."
)
MAX_TOKENS = 60


class SceneButton:
    def __init__(self, chip: int = 0, camera=None, camera_lock=None, vlm=None) -> None:
        self._tts = TtsSpeaker(model=TTS_MODEL)
        self._camera = camera or Picamera2Source(width=1280, height=720)
        self._camera_lock = camera_lock
        self._owns_camera = camera is None
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_input(self._chip, BUTTON_PIN, lgpio.SET_PULL_UP)
        self._vlm = vlm
        print(f"[scene_button] VLM backend={type(vlm).__name__ if vlm else 'none'}")

    def run(self) -> None:
        print(f"[scene_button] listening on GPIO {BUTTON_PIN} — press to describe scene")
        if self._owns_camera:
            self._camera.start()
        try:
            while True:
                if _button_pressed(self._chip, BUTTON_PIN):
                    print(f"[GPIO {BUTTON_PIN}] scene — describe surroundings")
                    self._handle()
        finally:
            if self._owns_camera:
                self._camera.stop()
            lgpio.gpiochip_close(self._chip)

    def _handle(self) -> None:
        t0 = time.perf_counter()
        with self._camera_lock if self._camera_lock else _nullcontext():
            frame = self._camera.capture_frame()
        frame_bgr = to_bgr(frame, input_is_rgb=getattr(self._camera, "output_is_rgb", False))
        t_cap = time.perf_counter() - t0
        print(f"[scene_button] captured in {1000*t_cap:.0f}ms — running VLM inference...")

        image_path = Path("/tmp/batglass_scene_btn.jpg")
        cv2.imwrite(str(image_path), frame_bgr)
        tokens = self._vlm.run(image_path=image_path, prompt=SCENE_PROMPT, max_tokens=MAX_TOKENS)
        print("[scene_button] streaming TTS")
        self._tts.speak_stream(tokens)
        print(f"[scene_button] done ({time.perf_counter()-t0:.1f}s total)")


def _button_pressed(chip: int, pin: int, debounce: float = 0.05) -> bool:
    """Return True once per press (active-low, waits for release)."""
    if lgpio.gpio_read(chip, pin) != 0:
        time.sleep(0.01)  # idle sleep to avoid busy-loop
        return False
    time.sleep(debounce)
    if lgpio.gpio_read(chip, pin) != 0:
        return False
    while lgpio.gpio_read(chip, pin) == 0:
        time.sleep(0.01)
    return True


if __name__ == "__main__":
    SceneButton().run()
