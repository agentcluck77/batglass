#!/usr/bin/env python3
import argparse
import sys
import time
from typing import Optional, Tuple

import pytesseract

try:
    import cv2
except ImportError:  # pragma: no cover - runtime dependency check
    cv2 = None

try:
    from picamera2 import Picamera2
except ImportError:  # pragma: no cover - runtime dependency check
    Picamera2 = None


def parse_roi(value: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    if not value:
        return None
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be x,y,w,h")
    try:
        x, y, w, h = (int(p.strip()) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ROI must be integers") from exc
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("ROI width/height must be > 0")
    return x, y, w, h


def rotate_frame(frame, angle: int):
    if angle == 0:
        return frame
    if angle == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError("rotate must be 0, 90, 180, or 270")


def preprocess(frame, input_is_rgb: bool, scale: float, threshold: bool):
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


def run_ocr(
    frame,
    input_is_rgb: bool,
    args,
):
    if args.roi:
        x, y, w, h = args.roi
        frame = frame[y : y + h, x : x + w]

    if args.rotate:
        frame = rotate_frame(frame, args.rotate)

    processed = preprocess(frame, input_is_rgb, args.scale, args.threshold)
    config = f"--oem {args.oem} --psm {args.psm}"
    text = pytesseract.image_to_string(processed, lang=args.lang, config=config)
    return clean_text(text)


def load_image(path: str):
    image = cv2.imread(path)
    if image is None:
        raise FileNotFoundError(f"Unable to read image: {path}")
    return image


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCR still images from Arducam and print text to terminal."
    )
    parser.add_argument("--interval-ms", type=int, default=1000, help="Loop interval")
    parser.add_argument("--width", type=int, default=1280, help="Capture width")
    parser.add_argument("--height", type=int, default=720, help="Capture height")
    parser.add_argument(
        "--rotate",
        type=int,
        default=0,
        choices=[0, 90, 180, 270],
        help="Rotate captured frame before OCR",
    )
    parser.add_argument("--roi", type=parse_roi, default=None, help="x,y,w,h crop")
    parser.add_argument("--scale", type=float, default=2.0, help="Resize factor")
    parser.add_argument(
        "--threshold",
        action="store_true",
        default=True,
        help="Use adaptive thresholding (default: on)",
    )
    parser.add_argument(
        "--no-threshold",
        dest="threshold",
        action="store_false",
        help="Disable thresholding",
    )
    parser.add_argument("--psm", type=int, default=6, help="Tesseract PSM mode")
    parser.add_argument("--oem", type=int, default=1, help="Tesseract OEM mode")
    parser.add_argument("--lang", type=str, default="eng", help="OCR language")
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="OCR a single image file and exit",
    )
    parser.add_argument(
        "--print-unchanged",
        action="store_true",
        help="Print text every loop even if unchanged",
    )

    args = parser.parse_args()

    if cv2 is None:
        print("Missing dependency: opencv-python. Install with uv.", file=sys.stderr)
        return 1

    if args.image:
        frame = load_image(args.image)
        text = run_ocr(frame, input_is_rgb=False, args=args)
        print(text)
        return 0

    if Picamera2 is None:
        print("Missing dependency: picamera2. Install via apt.", file=sys.stderr)
        return 1

    picam2 = Picamera2()
    config = picam2.create_still_configuration(main={"size": (args.width, args.height)})
    picam2.configure(config)
    picam2.start()
    time.sleep(1.0)

    last_text = None
    try:
        while True:
            frame = picam2.capture_array("main")
            text = run_ocr(frame, input_is_rgb=True, args=args)
            if args.print_unchanged or text != last_text:
                if text:
                    print(text)
                    print("-" * 40)
                last_text = text
            time.sleep(args.interval_ms / 1000.0)
    except KeyboardInterrupt:
        return 0
    finally:
        picam2.stop()
        picam2.close()


if __name__ == "__main__":
    raise SystemExit(main())
