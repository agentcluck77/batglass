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

from camera_ocr.camera import Picamera2Source
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


def main() -> None:
    faulthandler.enable(all_threads=True)
    faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)

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

    # Single shared camera + lock so OCR and scene don't conflict
    camera = Picamera2Source(width=CAMERA_WIDTH, height=CAMERA_HEIGHT)
    camera.start()
    camera_lock = threading.Lock()

    # Single shared VLM — Hailo-only, fail fast if the accelerator is unavailable.
    from batglass.hailo_vlm import HailoVlmRunner

    vlm = HailoVlmRunner()
    print("[buttons] VLM backend=hailo (shared)")

    feedback_beeper = Beeper()
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
        camera.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
