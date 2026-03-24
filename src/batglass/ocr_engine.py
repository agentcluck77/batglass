"""OCR engine — Tesseract primary, with per-word confidence scoring.

RapidOCR was benchmarked at ~4s on Pi 5 (CRNN recogniser bottleneck),
vs Tesseract at ~500ms. Tesseract is used as the fast path.
VLM fallback handles complex/angled/low-confidence cases.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
import pytesseract


@dataclass
class OcrResult:
    text: str
    confidence: float          # mean word confidence (0.0–100.0 from Tesseract)
    timing_ms: float = 0.0


class TesseractOcrEngine:
    """Tesseract 5 LSTM OCR engine.

    Benchmarked at ~500ms on Pi 5 for a 1200×630 image.
    Confidence is Tesseract's per-word score (0–100).
    """

    # Tesseract confidence threshold below which we escalate to VLM
    CONFIDENCE_THRESHOLD = 60.0

    def run(self, frame: Any) -> OcrResult:
        preprocessed = self._preprocess(frame)

        t0 = time.perf_counter()
        data = pytesseract.image_to_data(
            preprocessed,
            config="--oem 1 --psm 6",
            output_type=pytesseract.Output.DICT,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        words, scores = [], []
        for i, text in enumerate(data["text"]):
            word = str(text).strip()
            if not word:
                continue
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                continue
            if conf < 0:
                continue
            words.append(word)
            scores.append(conf)

        text = " ".join(words)
        mean_conf = sum(scores) / len(scores) if scores else 0.0

        return OcrResult(text=text, confidence=mean_conf, timing_ms=elapsed_ms)

    @staticmethod
    def _preprocess(frame: Any) -> np.ndarray:
        """Grayscale + adaptive threshold — standard Tesseract prep."""
        img = np.asarray(frame)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY if img.shape[2] == 3 else cv2.COLOR_RGB2GRAY)
        return cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31, 11,
        )
