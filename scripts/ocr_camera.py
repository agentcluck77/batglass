#!/usr/bin/env python3
"""Entrypoint for the modular OCR camera CLI.

This module keeps legacy helper exports for sibling scripts.
"""

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from camera_ocr.cli import main as cli_main
from camera_ocr.ocr import clean_text, parse_roi, preprocess, rotate_frame

__all__ = [
    "clean_text",
    "parse_roi",
    "preprocess",
    "rotate_frame",
    "main",
]


def main() -> int:
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
