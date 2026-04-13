#!/usr/bin/env python3
"""GPIO 17 — Scene button: press to describe surroundings with Gemini."""

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
BUTTON_PIN = 17

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# -----------------------------------------------------------------------------


def _load_config() -> dict:
    cfg_path = PROJECT_ROOT / "config.yaml"
    if cfg_path.exists():
        with open(cfg_path) as f:
            return yaml.safe_load(f) or {}
    return {}


SCENE_PROMPT = (
    "You are assisting a blind person. Describe this scene in two sentences or fewer. "
    "Focus first on any immediate dangers or obstacles such as steps, kerbs, traffic, "
    "wet floors, or moving objects. Then briefly describe the surroundings. "
    "Speak naturally and directly — no preamble."
)


class SceneButton:
    def __init__(self, chip: int = 0, camera=None, camera_lock=None, live=None) -> None:
        self._live = live
        self._camera = camera or Picamera2Source(width=1280, height=720)
        self._camera_lock = camera_lock
        self._owns_camera = camera is None
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_input(self._chip, BUTTON_PIN, lgpio.SET_PULL_UP)
        print(f"[scene_button] backend={type(live).__name__ if live else 'none'}")

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
        try:
            with self._camera_lock if self._camera_lock else _nullcontext():
                frame = self._camera.capture_frame()
        except Exception as exc:
            print(f"[scene_button] capture failed: {exc}")
            return
        frame_bgr = to_bgr(frame, input_is_rgb=getattr(self._camera, "output_is_rgb", False))
        t_cap = time.perf_counter()
        print(f"[scene_button] capture={1000*(t_cap-t0):.0f}ms")

        t_save0 = time.perf_counter()
        try:
            image_path = save_button_frame(frame_bgr, "scene", "button_scene")
        except Exception as exc:
            print(f"[scene_button] failed to save frame: {exc}")
            image_path = frame_bgr
        print(f"[scene_button] save={1000*(time.perf_counter()-t_save0):.0f}ms")

        if self._live is None:
            print("[scene_button] no live runner configured")
            return

        t_live0 = time.perf_counter()
        try:
            self._live.speak_image(image_path, SCENE_PROMPT)
        except Exception as exc:
            print(f"[scene_button] live request failed: {exc}")
        print(f"[scene_button] live={1000*(time.perf_counter()-t_live0):.0f}ms  total={1000*(time.perf_counter()-t0):.0f}ms")


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
    SceneButton().run()
