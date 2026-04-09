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

import signal
import sys
import threading

from camera_ocr.camera import Picamera2Source
from buttons.beep_button import BeepButton
from buttons.ocr_button import OcrButton
from buttons.scene_button import SceneButton
from buttons.volume_button import (
    VOLUME_DOWN_PIN,
    VOLUME_STEP_DB,
    VOLUME_UP_PIN,
    VolumeButton,
)
from proximity.beep import Beeper


def main() -> None:
    # Single shared camera + lock so OCR and scene don't conflict
    camera = Picamera2Source(width=1280, height=720)
    camera.start()
    camera_lock = threading.Lock()

    # Single shared VLM — the Hailo chip only supports one VDevice owner
    try:
        from batglass.hailo_vlm import HailoVlmRunner
        vlm = HailoVlmRunner()
        print("[buttons] VLM backend=hailo (shared)")
    except Exception as e:
        print(f"[buttons] Hailo VLM unavailable ({e}), falling back to CPU VLM")
        from batglass.vlm import VlmRunner
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        vlm = VlmRunner(
            model=root / "models/moondream2/moondream2-text-model-f16_ct-vicuna.gguf",
            mmproj=root / "models/moondream2/moondream2-mmproj-f16-20250414.gguf",
        )

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
