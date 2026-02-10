#!/usr/bin/env python3
"""Take a single photo from the Arducam, save it, and run OCR."""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from camera_ocr.ocr import clean_text, parse_roi, preprocess, rotate_frame

try:
    import cv2
except ImportError:
    cv2 = None

import pytesseract  # noqa: E402

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "captures"


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


def main() -> int:
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
        "--output-dir", type=Path, default=CAPTURES_DIR,
        help="Directory to save captured images",
    )

    args = parser.parse_args()

    if cv2 is None:
        print("Missing dependency: opencv-python. Install with uv.", file=sys.stderr)
        return 1

    # Capture with rpicam-still (handles autofocus natively)
    saved_path = snap(args.width, args.height, args.output_dir)
    print(f"Saved: {saved_path}")

    # Load the saved image for OCR
    frame = cv2.imread(str(saved_path))
    if frame is None:
        print(f"Failed to load captured image: {saved_path}", file=sys.stderr)
        return 1

    # OCR
    ocr_frame = frame
    if args.roi:
        x, y, w, h = args.roi
        ocr_frame = ocr_frame[y : y + h, x : x + w]
    if args.rotate:
        ocr_frame = rotate_frame(ocr_frame, args.rotate)

    processed = preprocess(ocr_frame, input_is_rgb=False, scale=args.scale, threshold=args.threshold)
    config = f"--oem {args.oem} --psm {args.psm}"
    text = clean_text(pytesseract.image_to_string(processed, lang=args.lang, config=config))

    if text:
        print("-" * 40)
        print(text)
        print("-" * 40)
    else:
        print("No text detected.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
