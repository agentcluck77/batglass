#!/usr/bin/env python3
"""GPIO 17 — Scene button: Hailo YOLOv8 if available, else VLM fallback."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import contextlib
import cv2
import lgpio
import numpy as np

_nullcontext = contextlib.nullcontext

from batglass.tts import TtsSpeaker
from camera_ocr.camera import Picamera2Source, to_bgr

# -- config -------------------------------------------------------------------
BUTTON_PIN  = 17
HAILO_MODEL = "/usr/share/hailo-models/yolov8m_h10.hef"
CONF_THRESH = 0.5

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TTS_MODEL    = PROJECT_ROOT / "models/piper/en_US-lessac-medium.onnx"
VLM_MODEL    = PROJECT_ROOT / "models/moondream2/moondream2-text-model-f16_ct-vicuna.gguf"
VLM_MMPROJ   = PROJECT_ROOT / "models/moondream2/moondream2-mmproj-f16-20250414.gguf"
# -----------------------------------------------------------------------------

SCENE_PROMPT = "Describe what you see in this image in one or two sentences."

COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]


def _try_load_hailo():
    try:
        import subprocess
        result = subprocess.run(["hailortcli", "fw-control", "identify"],
                                capture_output=True, timeout=3)
        if result.returncode != 0:
            return None
        from picamera2.devices.hailo.hailo import Hailo
        h = Hailo(HAILO_MODEL)
        print("[scene_button] Hailo loaded OK")
        return h
    except Exception as e:
        print(f"[scene_button] Hailo unavailable ({e}), using VLM fallback")
        return None


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

        from batglass.stt import SttRunner
        whisper_model = PROJECT_ROOT / "whisper.cpp/models/ggml-base.en.bin"
        self._stt = SttRunner(model=whisper_model) if whisper_model.exists() else None

    def run(self) -> None:
        print(f"[scene_button] listening on GPIO {BUTTON_PIN} — hold to speak, release to process")
        if self._owns_camera:
            self._camera.start()
        try:
            while True:
                if _button_down(self._chip, BUTTON_PIN):
                    print("[scene_button] pressed — recording question")
                    self._handle()
        finally:
            if self._owns_camera:
                self._camera.stop()
            lgpio.gpiochip_close(self._chip)

    def _handle(self) -> None:
        import threading
        t0 = time.perf_counter()

        # Start STT recording immediately on press
        if self._stt is not None:
            self._stt.start_recording()

        # Capture image in parallel while user is still speaking
        frame_holder: list = []

        def do_capture():
            with self._camera_lock if self._camera_lock else _nullcontext():
                frame = self._camera.capture_frame()
            frame_holder.append(
                to_bgr(frame, input_is_rgb=getattr(self._camera, "output_is_rgb", False))
            )

        t_cap = threading.Thread(target=do_capture, daemon=True)
        t_cap.start()

        # Wait for button release, then stop recording
        _wait_for_release(self._chip, BUTTON_PIN)
        t_held = time.perf_counter() - t0
        print(f"[scene_button] released after {t_held:.1f}s — transcribing")

        question = ""
        if self._stt is not None:
            question = self._stt.stop_and_transcribe().strip()

        t_cap.join()

        if not frame_holder:
            self._tts.speak("Sorry, I could not capture an image.")
            return

        frame = frame_holder[0]
        t_ready = time.perf_counter() - t0
        print(f"[scene_button] question={repr(question)} ready={t_ready:.1f}s")

        prompt = question if question else SCENE_PROMPT
        image_path = Path("/tmp/batglass_scene_btn.jpg")
        cv2.imwrite(str(image_path), frame)
        tokens = self._vlm.run(image_path=image_path, prompt=prompt, max_tokens=100)
        self._tts.speak_stream(tokens)


def _parse_detections(output, threshold: float) -> list[str]:
    """Parse Hailo YOLOv8 output into class names.

    picamera2's Hailo wrapper returns a list of arrays, one per COCO class,
    each with shape (N, 5): [x1, y1, x2, y2, score] — class index is the
    list position, not a column.
    """
    names = []
    if isinstance(output, list):
        # Per-class list: output[class_id] = array of shape (N, 5)
        for class_id, detections in enumerate(output):
            if class_id >= len(COCO_CLASSES):
                break
            for det in detections:
                if len(det) >= 5 and float(det[4]) >= threshold:
                    names.append(COCO_CLASSES[class_id])
    else:
        # Dict fallback (older format): values have shape (N, 6) with class in col 5
        for arr in output.values():
            for det in arr.reshape(-1, arr.shape[-1]):
                if len(det) >= 6 and float(det[4]) >= threshold:
                    class_id = int(det[5])
                    if 0 <= class_id < len(COCO_CLASSES):
                        names.append(COCO_CLASSES[class_id])
    return names


def _build_description(names: list[str]) -> str:
    if not names:
        return "I don't see anything recognisable."
    counts = Counter(names)
    parts = [f"{n} {k}s" if n > 1 else f"a {k}" for k, n in counts.most_common()]
    if len(parts) == 1:
        return f"I can see {parts[0]}."
    return "I can see " + ", ".join(parts[:-1]) + f" and {parts[-1]}."


def _button_down(chip: int, pin: int, debounce: float = 0.05) -> bool:
    """Return True once the button is pressed (active-low). Does NOT wait for release."""
    if lgpio.gpio_read(chip, pin) != 0:
        time.sleep(0.01)  # idle sleep to avoid busy-loop
        return False
    time.sleep(debounce)
    return lgpio.gpio_read(chip, pin) == 0


def _wait_for_release(chip: int, pin: int) -> None:
    """Block until the button is released."""
    while lgpio.gpio_read(chip, pin) == 0:
        time.sleep(0.01)


if __name__ == "__main__":
    SceneButton().run()
