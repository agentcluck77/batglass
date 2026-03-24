#!/usr/bin/env python3
"""CLI: snap a photo from the Arducam, save it, and run OCR."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .ocr import OcrConfig, OcrService, parse_roi
from .vlm import ocr_with_llm

try:
    import cv2
except ImportError:
    cv2 = None

_DEFAULT_CAPTURES_DIR = Path(__file__).resolve().parent.parent.parent / "captures"


def snap(width: int, height: int, output_dir: Path) -> Path:
    """Capture a focused still using rpicam-still and return the saved path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = output_dir / f"snap_{ts}.jpg"
    cmd = [
        "rpicam-still",
        "--width", str(width),
        "--height", str(height),
        "--autofocus-mode", "auto",
        "--output", str(path),
        "--nopreview",
        "--timeout", "3000",
    ]
    print("Capturing with autofocus...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"rpicam-still failed (exit {result.returncode})")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Snap a photo from the Arducam, save it, and run OCR."
    )
    parser.add_argument("--width", type=int, default=1280, help="Capture width")
    parser.add_argument("--height", type=int, default=720, help="Capture height")
    parser.add_argument(
        "--rotate", type=int, default=0, choices=[0, 90, 180, 270],
        help="Rotate frame before OCR",
    )
    parser.add_argument("--roi", type=parse_roi, default=None, help="x,y,w,h crop")
    parser.add_argument("--scale", type=float, default=2.0, help="Resize factor")
    parser.add_argument(
        "--threshold", action="store_true", default=True,
        help="Use adaptive thresholding (default: on)",
    )
    parser.add_argument(
        "--no-threshold", dest="threshold", action="store_false",
        help="Disable thresholding",
    )
    parser.add_argument("--psm", type=int, default=6, help="Tesseract PSM mode")
    parser.add_argument("--oem", type=int, default=1, help="Tesseract OEM mode")
    parser.add_argument("--lang", type=str, default="eng", help="OCR language")
    parser.add_argument(
        "--output-dir", type=Path, default=_DEFAULT_CAPTURES_DIR,
        help="Directory to save captured images",
    )
    parser.add_argument(
        "--image", type=Path, default=None,
        help="Read an existing image instead of capturing a new one",
    )
    parser.add_argument(
        "--llm", action="store_true", default=False,
        help="Use Ollama vision model instead of Tesseract",
    )
    parser.add_argument(
        "--model", type=str, default="moondream",
        help="Ollama model to use with --llm (default: moondream)",
    )

    args = parser.parse_args(argv)

    if cv2 is None:
        print("Missing dependency: opencv-python. Install with uv.", file=sys.stderr)
        return 1

    if args.image:
        saved_path = args.image.resolve()
        if not saved_path.exists():
            print(f"Image not found: {saved_path}", file=sys.stderr)
            return 1
        print(f"Using: {saved_path}")
    else:
        saved_path = snap(args.width, args.height, args.output_dir)
        print(f"Saved: {saved_path}")

    if args.llm:
        print(f"Running OCR with Ollama ({args.model})...")
        text = ocr_with_llm(saved_path, args.model)
    else:
        frame = cv2.imread(str(saved_path))
        if frame is None:
            print(f"Failed to load captured image: {saved_path}", file=sys.stderr)
            return 1

        cfg = OcrConfig(
            lang=args.lang,
            psm=args.psm,
            oem=args.oem,
            rotate=args.rotate,
            scale=args.scale,
            threshold=args.threshold,
            input_is_rgb=False,
        )
        result = OcrService().recognize(frame, cfg)
        text = result.text

    if text:
        print("-" * 40)
        print(text)
        print("-" * 40)
    else:
        print("No text detected.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
