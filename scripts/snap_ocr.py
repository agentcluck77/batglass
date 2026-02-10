#!/usr/bin/env python3
"""Take a single photo from the Arducam, save it, and run OCR."""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Allow importing sibling module
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ocr_camera import clean_text, parse_roi, preprocess, rotate_frame

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

import pytesseract

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "captures"


def snap(width: int, height: int) -> "cv2.Mat":
    """Capture a single still frame and return it."""
    picam2 = Picamera2()
    config = picam2.create_still_configuration(main={"size": (width, height)})
    picam2.configure(config)
    picam2.start()
    time.sleep(1.0)
    frame = picam2.capture_array("main")
    picam2.stop()
    picam2.close()
    return frame


def save_image(frame, output_dir: Path) -> Path:
    """Save frame as a timestamped JPEG and return the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = output_dir / f"snap_{ts}.jpg"
    # picamera2 returns RGB; cv2.imwrite expects BGR
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), bgr)
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
    if Picamera2 is None:
        print("Missing dependency: picamera2. Install via apt.", file=sys.stderr)
        return 1

    # Capture
    print("Capturing image...")
    frame = snap(args.width, args.height)

    # Save
    saved_path = save_image(frame, args.output_dir)
    print(f"Saved: {saved_path}")

    # OCR
    ocr_frame = frame
    if args.roi:
        x, y, w, h = args.roi
        ocr_frame = ocr_frame[y : y + h, x : x + w]
    if args.rotate:
        ocr_frame = rotate_frame(ocr_frame, args.rotate)

    processed = preprocess(ocr_frame, input_is_rgb=True, scale=args.scale, threshold=args.threshold)
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
