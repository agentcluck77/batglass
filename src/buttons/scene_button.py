#!/usr/bin/env python3
"""GPIO 17 — Scene button: press to describe surroundings with Gemini."""

from __future__ import annotations

import time
from pathlib import Path

import contextlib
import cv2
import lgpio
import yaml

_nullcontext = contextlib.nullcontext

from batglass.tts import TtsSpeaker
from buttons.artifacts import (
    save_button_artifact,
    save_button_frame,
    save_upscaled_artifact,
)
from camera_ocr.camera import Picamera2Source, to_bgr

# -- config -------------------------------------------------------------------
BUTTON_PIN = 17

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TTS_MODEL    = PROJECT_ROOT / "models/piper/en_US-lessac-medium.onnx"
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
    "wet floors, or moving objects. Then briefly describe the surroundings."
)
MAX_TOKENS = 40


class SceneButton:
    def __init__(self, chip: int = 0, camera=None, camera_lock=None, vlm=None) -> None:
        cfg = _load_config()
        scene_cfg = cfg.get("scene", {})
        self._max_tokens = int(scene_cfg.get("max_tokens", MAX_TOKENS))
        self._tts = TtsSpeaker(model=TTS_MODEL)
        self._camera = camera or Picamera2Source(width=1280, height=720)
        self._camera_lock = camera_lock
        self._owns_camera = camera is None
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_input(self._chip, BUTTON_PIN, lgpio.SET_PULL_UP)
        self._vlm = vlm
        print(f"[scene_button] backend={type(vlm).__name__ if vlm else 'none'}")

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
            self._tts.speak("The camera is not available right now.")
            return
        frame_bgr = to_bgr(frame, input_is_rgb=getattr(self._camera, "output_is_rgb", False))
        t_cap = time.perf_counter() - t0
        print(f"[scene_button] captured in {1000*t_cap:.0f}ms — running Gemini inference...")

        try:
            image_path = save_button_frame(frame_bgr, "scene", "button_scene")
            print(f"[scene_button] saved frame: {image_path}")
        except Exception as exc:
            print(f"[scene_button] failed to save frame: {exc}")
            image_path = frame_bgr
        self._save_gemini_input(image_path)
        if self._vlm is None:
            self._tts.speak("Gemini is not available.")
            return

        def _gemini_tokens():
            saw_output = False
            try:
                for token in self._vlm.run(
                    image_path=image_path,
                    prompt=SCENE_PROMPT,
                    max_tokens=self._max_tokens,
                ):
                    saw_output = True
                    yield token
            except Exception as exc:
                print(f"[scene_button] Gemini request failed: {exc}")
                if not saw_output:
                    yield "I could not describe the scene right now."
                return

            if not saw_output:
                yield "I could not describe the scene right now."

        print("[scene_button] streaming TTS")
        self._tts.speak_stream(_tee_tokens(_gemini_tokens(), "[scene_button] text:"))
        print(f"[scene_button] done ({time.perf_counter()-t0:.1f}s total)")

    def _save_gemini_input(self, image_source) -> None:
        preprocess = getattr(self._vlm, "preprocess_image", None)
        if preprocess is None:
            return
        try:
            gemini_rgb = preprocess(image_source)
            gemini_bgr = cv2.cvtColor(gemini_rgb, cv2.COLOR_RGB2BGR)
            saved_gemini = save_button_artifact(
                gemini_bgr,
                "scene",
                "button_scene_gemini_input",
            )
            print(f"[scene_button] saved Gemini input: {saved_gemini}")
            saved_preview = save_upscaled_artifact(
                gemini_bgr,
                "scene",
                "button_scene_gemini_input_preview",
            )
            print(f"[scene_button] saved Gemini input preview: {saved_preview}")
        except Exception as exc:
            print(f"[scene_button] failed to save Gemini input: {exc}")


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
    while lgpio.gpio_read(chip, pin) == 0:
        time.sleep(0.01)
    return True


if __name__ == "__main__":
    SceneButton().run()
