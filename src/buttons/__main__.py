#!/usr/bin/env python3
"""Run all button listeners concurrently.

    GPIO 17 — scene description
    GPIO 27 — OCR
    GPIO 22 — beep
    GPIO 5  — volume up
    GPIO 6  — volume down

Usage:
    python -m buttons
"""

from __future__ import annotations

import faulthandler
import signal
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from camera_ocr.camera import Picamera2Source
import lgpio
import yaml
from buttons.beep_button import BeepButton
from buttons.ocr_button import OcrButton
from buttons.scene_button import SceneButton
from buttons.volume_button import (
    DEFAULT_STARTUP_VOLUME_PERCENT,
    VOLUME_DOWN_PIN,
    VOLUME_STEP_DB,
    VOLUME_UP_PIN,
    VolumeButton,
    set_startup_volume,
)
from proximity.beep import Beeper

CAMERA_WIDTH = 2592
CAMERA_HEIGHT = 1944
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _UnavailableCamera:
    output_is_rgb = True

    def __init__(self, message: str) -> None:
        self._message = message

    def start(self) -> None:
        return

    def capture_frame(self):
        raise RuntimeError(self._message)

    def stop(self) -> None:
        return


def _load_config() -> dict:
    cfg_path = PROJECT_ROOT / "config.yaml"
    if cfg_path.exists():
        with open(cfg_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    faulthandler.enable(all_threads=True)
    faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)
    cfg = _load_config()

    try:
        startup_level = set_startup_volume(DEFAULT_STARTUP_VOLUME_PERCENT)
    except Exception as exc:
        print(f"[buttons] failed to set startup volume: {exc}")
    else:
        if startup_level is None:
            print(
                f"[buttons] startup volume set to {DEFAULT_STARTUP_VOLUME_PERCENT}%"
            )
        else:
            print(f"[buttons] startup volume -> {startup_level.percent}%")

    # Single shared camera + lock so OCR and scene don't conflict.
    camera = Picamera2Source(width=CAMERA_WIDTH, height=CAMERA_HEIGHT)
    try:
        camera.start()
    except Exception as exc:
        print(f"[buttons] camera unavailable: {exc}")
        print("[buttons] scene/OCR buttons will stay active and announce the camera issue when pressed")
        camera = _UnavailableCamera(str(exc))
    camera_lock = threading.Lock()

    # Single shared Gemini vision client for scene description and OCR.
    from batglass.gemini_vlm import GeminiVlmRunner

    gemini_cfg = cfg.get("gemini", {})
    model = gemini_cfg.get("model", "gemini-3.1-flash-lite-preview")
    vlm = GeminiVlmRunner(model=model)
    print(f"[buttons] VLM backend=gemini model={model} (shared)")

    feedback_beeper = Beeper()
    try:
        beep_btn  = BeepButton()
        ocr_btn   = OcrButton(camera=camera, camera_lock=camera_lock, vlm=vlm)
        scene_btn = SceneButton(camera=camera, camera_lock=camera_lock, vlm=vlm)
        volume_up_btn = VolumeButton(
            pin=VOLUME_UP_PIN,
            delta_db=VOLUME_STEP_DB,
            feedback_beeper=feedback_beeper,
        )
        volume_down_btn = VolumeButton(
            pin=VOLUME_DOWN_PIN,
            delta_db=-VOLUME_STEP_DB,
            feedback_beeper=feedback_beeper,
        )
    except lgpio.error as exc:
        detail = str(exc)
        release = getattr(vlm, "release", None)
        if callable(release):
            release()
        camera.stop()
        if "GPIO busy" in detail:
            raise SystemExit(
                "[buttons] GPIO busy: another BatGlass button runtime is probably already running. "
                "Stop `batglass.service` or terminate the existing `python -m buttons.__main__` process first."
            )
        raise SystemExit(f"[buttons] failed to claim GPIO inputs: {detail}")
    threads = [
        threading.Thread(target=beep_btn.run,  name="beep",  daemon=True),
        threading.Thread(target=ocr_btn.run,   name="ocr",   daemon=True),
        threading.Thread(target=scene_btn.run, name="scene", daemon=True),
        threading.Thread(target=volume_up_btn.run, name="volume-up", daemon=True),
        threading.Thread(target=volume_down_btn.run, name="volume-down", daemon=True),
    ]

    for t in threads:
        t.start()

    print("[buttons] all listeners started — Ctrl+C to stop")

    def _shutdown(sig, frame):
        print("\n[buttons] shutting down")
        release = getattr(vlm, "release", None)
        if callable(release):
            release()
        camera.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
