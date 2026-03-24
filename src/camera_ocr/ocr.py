#!/usr/bin/env python3
"""OCR layer for camera/image text recognition."""

from __future__ import annotations

import argparse
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional, Tuple

import pytesseract

try:
    import cv2
except ImportError:  # pragma: no cover - runtime dependency check
    cv2 = None


def parse_roi(value: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    """Backward-compatible ROI parser kept for older callers."""
    if not value:
        return None
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be x,y,w,h")
    try:
        x, y, w, h = (int(part.strip()) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ROI must be integers") from exc
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("ROI width/height must be > 0")
    return x, y, w, h


def rotate_frame(frame: Any, angle: int):
    if cv2 is None:
        raise RuntimeError("Missing dependency: opencv-python. Install with uv.")
    if angle == 0:
        return frame
    if angle == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError("rotate must be 0, 90, 180, or 270")


def preprocess(frame: Any, input_is_rgb: bool, scale: float, threshold: bool):
    if cv2 is None:
        raise RuntimeError("Missing dependency: opencv-python. Install with uv.")
    if input_is_rgb:
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    else:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    if scale and scale != 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    if threshold:
        gray = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
    return gray


def clean_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines).strip()


@dataclass(slots=True)
class OcrConfig:
    lang: str = "eng"
    psm: int = 6
    oem: int = 1
    rotate: int = 0
    scale: float = 2.0
    threshold: bool = True
    input_is_rgb: bool = False


@dataclass(slots=True)
class OcrBox:
    text: str
    confidence: float
    x: int
    y: int
    w: int
    h: int


@dataclass(slots=True)
class OcrResult:
    text: str
    avg_confidence: float
    boxes: list[OcrBox]
    timing_ms: dict[str, float]
    processed_frame: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "avg_confidence": self.avg_confidence,
            "timing_ms": self.timing_ms,
            "boxes": [asdict(box) for box in self.boxes],
        }


class TesseractAdapter:
    def _config(self, cfg: OcrConfig) -> str:
        return f"--oem {cfg.oem} --psm {cfg.psm}"

    def image_to_data(self, processed: Any, cfg: OcrConfig) -> dict[str, list[Any]]:
        return pytesseract.image_to_data(
            processed,
            lang=cfg.lang,
            config=self._config(cfg),
            output_type=pytesseract.Output.DICT,
        )

    def image_to_string(self, processed: Any, cfg: OcrConfig) -> str:
        return pytesseract.image_to_string(
            processed,
            lang=cfg.lang,
            config=self._config(cfg),
        )


class OcrService:
    def __init__(self, adapter: Optional[TesseractAdapter] = None):
        self._adapter = adapter or TesseractAdapter()

    def recognize(self, frame: Any, cfg: OcrConfig) -> OcrResult:
        total_start = time.perf_counter()

        rotated = rotate_frame(frame, cfg.rotate)

        preprocess_start = time.perf_counter()
        processed = preprocess(rotated, cfg.input_is_rgb, cfg.scale, cfg.threshold)
        preprocess_ms = (time.perf_counter() - preprocess_start) * 1000.0

        ocr_start = time.perf_counter()
        text = self._adapter.image_to_string(processed, cfg)
        data = self._adapter.image_to_data(processed, cfg)
        ocr_ms = (time.perf_counter() - ocr_start) * 1000.0

        boxes = self._extract_boxes(data)
        avg_confidence = self._average_confidence(boxes)
        total_ms = (time.perf_counter() - total_start) * 1000.0

        return OcrResult(
            text=clean_text(text),
            avg_confidence=avg_confidence,
            boxes=boxes,
            timing_ms={
                "preprocess": preprocess_ms,
                "ocr": ocr_ms,
                "total": total_ms,
            },
            processed_frame=processed,
        )

    @staticmethod
    def _extract_boxes(data: dict[str, list[Any]]) -> list[OcrBox]:
        boxes: list[OcrBox] = []

        texts = data.get("text", [])
        confs = data.get("conf", [])
        lefts = data.get("left", [])
        tops = data.get("top", [])
        widths = data.get("width", [])
        heights = data.get("height", [])

        for idx, text in enumerate(texts):
            clean = str(text).strip()
            conf = OcrService._parse_conf(confs, idx)
            if not clean or conf < 0:
                continue

            boxes.append(
                OcrBox(
                    text=clean,
                    confidence=conf,
                    x=int(lefts[idx]),
                    y=int(tops[idx]),
                    w=int(widths[idx]),
                    h=int(heights[idx]),
                )
            )

        return boxes

    @staticmethod
    def _parse_conf(confs: list[Any], idx: int) -> float:
        try:
            return float(confs[idx])
        except (IndexError, TypeError, ValueError):
            return -1.0

    @staticmethod
    def _average_confidence(boxes: list[OcrBox]) -> float:
        if not boxes:
            return 0.0
        return sum(box.confidence for box in boxes) / len(boxes)
