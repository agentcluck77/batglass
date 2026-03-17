"""OCR mode — tap button → read text aloud."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from batglass.ocr_engine import TesseractOcrEngine
    from batglass.tts import TtsSpeaker


class OcrMode:
    """Capture an image, OCR it, speak the result.

    Fast path  : RapidOCR (200–450 ms) — used when confidence ≥ threshold
    Fallback   : VLM via llama-mtmd-cli — used when confidence < threshold
                 (requires vlm: VlmRunner to be passed in)
    """

    def __init__(
        self,
        ocr: TesseractOcrEngine,
        tts: TtsSpeaker,
        camera,
        vlm=None,
    ) -> None:
        self._ocr = ocr
        self._tts = tts
        self._camera = camera
        self._vlm = vlm

    def run(self) -> None:
        t0 = time.perf_counter()

        frame = self._camera.capture_frame()
        t_capture = time.perf_counter()

        result = self._ocr.run(frame)
        t_ocr = time.perf_counter()

        from batglass.ocr_engine import TesseractOcrEngine
        if result.text and result.confidence >= TesseractOcrEngine.CONFIDENCE_THRESHOLD:
            print(
                f"[ocr] RapidOCR conf={result.confidence:.2f} "
                f"capture={1000*(t_capture-t0):.0f}ms "
                f"ocr={1000*(t_ocr-t_capture):.0f}ms"
            )
            self._tts.speak(result.text)
            return

        # Low confidence or no text — try VLM fallback
        if self._vlm is None:
            msg = result.text if result.text else "No text found."
            print(f"[ocr] no VLM fallback, conf={result.confidence:.2f}, speaking raw result")
            self._tts.speak(msg)
            return

        print(
            f"[ocr] low conf={result.confidence:.2f}, escalating to VLM "
            f"capture={1000*(t_capture-t0):.0f}ms "
            f"ocr={1000*(t_ocr-t_capture):.0f}ms"
        )

        # Save frame for VLM
        image_path = Path("/tmp/batglass_ocr_frame.jpg")
        import cv2
        cv2.imwrite(str(image_path), frame)

        tokens = self._vlm.run(
            image_path=image_path,
            prompt="Transcribe all text visible in this image. Only output the text, nothing else.",
            max_tokens=150,
        )
        self._tts.speak_stream(tokens)
