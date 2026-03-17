"""OCR camera package."""

from .cli import OcrCameraCli, main
from .ocr import OcrBox, OcrConfig, OcrResult, OcrService, clean_text, parse_roi, preprocess, rotate_frame
from .vlm import ocr_with_llm

__all__ = [
    "OcrCameraCli",
    "OcrService",
    "OcrConfig",
    "OcrResult",
    "OcrBox",
    "clean_text",
    "parse_roi",
    "preprocess",
    "rotate_frame",
    "ocr_with_llm",
    "main",
]
