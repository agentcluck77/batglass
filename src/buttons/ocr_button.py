#!/usr/bin/env python3
"""GPIO 27 — OCR button: capture image → OCR → TTS."""

from __future__ import annotations

import time
from pathlib import Path
import re

import contextlib
import cv2
import lgpio
import yaml

_nullcontext = contextlib.nullcontext

from batglass.ocr_engine import TesseractOcrEngine
from batglass.tts import TtsSpeaker
from buttons.artifacts import (
    save_button_artifact,
    save_button_frame,
    save_upscaled_artifact,
)
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

OCR_PROMPT = (
    "Read the text in this image and reply with only the exact text from the image. "
    "Do not add explanations, prefixes, quotes, or labels. "
    "If no readable text is present, reply with NO_TEXT."
)
OCR_MAX_TOKENS = 60


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
        try:
            saved_frame = save_button_frame(frame_bgr, "ocr", "button_ocr")
            print(f"[ocr_button] saved frame: {saved_frame}")
        except Exception as exc:
            print(f"[ocr_button] failed to save frame: {exc}")
            saved_frame = None

        if self._ocr_engine == "vlm":
            # Skip Tesseract entirely
            print(f"[ocr_button] VLM mode capture={1000*(t_cap-t0):.0f}ms")
            if self._vlm is None:
                self._tts.speak("VLM not available.")
                return
            self._save_vlm_input(saved_frame or frame_bgr)
            print("[ocr_button] running VLM inference...")
            tokens = self._vlm.run(
                image_path=saved_frame or frame_bgr,
                prompt=OCR_PROMPT,
                max_tokens=OCR_MAX_TOKENS,
            )
            text = _collect_tokens(tokens)
            cleaned = _clean_vlm_ocr_text(text)
            print(f"[ocr_button] text: {cleaned!r}")
            self._tts.speak(cleaned if cleaned != "NO_TEXT" else "No text found.")
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
        self._save_vlm_input(saved_frame or frame_bgr)
        tokens = self._vlm.run(
            image_path=saved_frame or frame_bgr,
            prompt=OCR_PROMPT,
            max_tokens=OCR_MAX_TOKENS,
        )
        text = _collect_tokens(tokens)
        cleaned = _clean_vlm_ocr_text(text)
        print(f"[ocr_button] text: {cleaned!r}")
        self._tts.speak(cleaned if cleaned != "NO_TEXT" else "No text found.")

    def _save_vlm_input(self, image_source) -> None:
        preprocess = getattr(self._vlm, "preprocess_image", None)
        if preprocess is None:
            return
        try:
            vlm_rgb = preprocess(image_source)
            vlm_bgr = cv2.cvtColor(vlm_rgb, cv2.COLOR_RGB2BGR)
            saved_vlm = save_button_artifact(vlm_bgr, "ocr", "button_ocr_vlm_input")
            print(f"[ocr_button] saved VLM input: {saved_vlm}")
            saved_preview = save_upscaled_artifact(
                vlm_bgr,
                "ocr",
                "button_ocr_vlm_input_preview",
            )
            print(f"[ocr_button] saved VLM input preview: {saved_preview}")
        except Exception as exc:
            print(f"[ocr_button] failed to save VLM input: {exc}")


def _tee_tokens(tokens, label: str):
    """Yield tokens unchanged while printing them to stdout for debugging."""
    buf = []
    for tok in tokens:
        buf.append(tok)
        yield tok
    print(f"{label} {''.join(buf)!r}")


def _collect_tokens(tokens) -> str:
    return "".join(tokens).strip()


def _clean_vlm_ocr_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = cleaned.split("<|im_end|>", 1)[0].strip()
    cleaned = re.sub(
        r'^\s*(?:the\s+text\s+(?:visible\s+)?in\s+the\s+image\s+is|visible\s+text|text)\s*:\s*',
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()

    return cleaned or "NO_TEXT"


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
