#!/usr/bin/env python3
"""CLI layer for OCR camera testing."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import cv2
except ImportError:  # pragma: no cover - runtime dependency check
    cv2 = None

from .camera import ImageFileReader, Picamera2Source, to_bgr
from .ocr import OcrConfig, OcrResult, OcrService


class ResultPrinter:
    def print_result(self, result: OcrResult) -> None:
        print("TEXT:")
        print(result.text if result.text else "[no text detected]")
        print(f"AVG_CONFIDENCE: {result.avg_confidence:.2f}")
        print(
            "TIMING_MS: "
            f"preprocess={result.timing_ms['preprocess']:.2f} "
            f"ocr={result.timing_ms['ocr']:.2f} "
            f"total={result.timing_ms['total']:.2f}"
        )
        print("BOXES:")

        if not result.boxes:
            print("[none]")
            print("-" * 40)
            return

        for idx, box in enumerate(result.boxes, start=1):
            print(
                f"{idx}. text=\"{box.text}\" "
                f"conf={box.confidence:.2f} "
                f"bbox=({box.x},{box.y},{box.w},{box.h})"
            )
        print("-" * 40)


class ArtifactWriter:
    def __init__(self, output_dir: Path | str = "photos"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _stamp(self, name_hint: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"{ts}_{name_hint}"

    def save_frame(self, frame, name_hint: str, input_is_rgb: bool) -> Path:
        if cv2 is None:
            raise RuntimeError("Missing dependency: opencv-python. Install with uv.")

        path = self.output_dir / f"{self._stamp(name_hint)}.jpg"
        image = to_bgr(frame, input_is_rgb=input_is_rgb)
        ok = cv2.imwrite(str(path), image)
        if not ok:
            raise RuntimeError(f"Failed to save frame to {path}")
        return path

    def save_annotated(self, result: OcrResult, name_hint: str) -> Optional[Path]:
        if cv2 is None or result.processed_frame is None:
            return None

        processed = result.processed_frame
        if len(processed.shape) == 2:
            annotated = cv2.cvtColor(processed, cv2.COLOR_GRAY2BGR)
        else:
            annotated = processed.copy()

        for box in result.boxes:
            cv2.rectangle(
                annotated,
                (box.x, box.y),
                (box.x + box.w, box.y + box.h),
                (0, 255, 0),
                2,
            )

        path = self.output_dir / f"{self._stamp(name_hint)}_annotated.jpg"
        ok = cv2.imwrite(str(path), annotated)
        if not ok:
            raise RuntimeError(f"Failed to save annotated image to {path}")
        return path

    def save_result(self, result: OcrResult, name_hint: str) -> Path:
        path = self.output_dir / f"{self._stamp(name_hint)}.json"
        payload = result.to_dict()
        payload["box_coordinate_space"] = "processed_frame"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path


class OcrCameraCli:
    def __init__(self):
        self._ocr = OcrService()
        self._printer = ResultPrinter()
        self._writer: Optional[ArtifactWriter] = None

    def run(self, argv: Optional[list[str]] = None) -> int:
        parser = self._build_parser()
        args = parser.parse_args(argv)

        self._writer = ArtifactWriter(args.output_dir)

        try:
            return args.func(args)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # pragma: no cover - runtime safety
            print(str(exc), file=sys.stderr)
            return 1

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="CLI tool for testing OCR capability with the current camera source."
        )
        subparsers = parser.add_subparsers(dest="command", required=True)

        preview = subparsers.add_parser("preview", help="Live camera preview")
        self._add_camera_options(preview)
        self._add_output_option(preview)
        preview.set_defaults(func=self._cmd_preview)

        capture_once = subparsers.add_parser(
            "capture-once", help="Capture one frame and run OCR"
        )
        self._add_camera_options(capture_once)
        self._add_ocr_options(capture_once)
        self._add_output_option(capture_once)
        capture_once.set_defaults(func=self._cmd_capture_once)

        capture_interval = subparsers.add_parser(
            "capture-interval",
            help="Capture frames on an interval and run OCR repeatedly",
        )
        self._add_camera_options(capture_interval)
        self._add_ocr_options(capture_interval)
        self._add_output_option(capture_interval)
        capture_interval.add_argument(
            "--interval-ms",
            type=int,
            default=1000,
            help="Time between captures in milliseconds",
        )
        capture_interval.add_argument(
            "--count",
            type=int,
            default=None,
            help="Number of captures before exit (default: run until Ctrl+C)",
        )
        capture_interval.add_argument(
            "--no-save",
            action="store_true",
            help="Run OCR continuously without saving artifacts to disk",
        )
        capture_interval.set_defaults(func=self._cmd_capture_interval)

        ocr_from_file = subparsers.add_parser(
            "ocr-from-file", help="Run OCR on an image file"
        )
        self._add_ocr_options(ocr_from_file)
        self._add_output_option(ocr_from_file)
        ocr_from_file.add_argument("image", type=str, help="Image path")
        ocr_from_file.set_defaults(func=self._cmd_ocr_from_file)

        return parser

    @staticmethod
    def _add_camera_options(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--width", type=int, default=1280, help="Capture width")
        parser.add_argument("--height", type=int, default=720, help="Capture height")

    @staticmethod
    def _add_output_option(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--output-dir",
            type=Path,
            default=Path("photos"),
            help="Directory to save captured images and OCR results",
        )

    @staticmethod
    def _add_ocr_options(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--rotate",
            type=int,
            default=0,
            choices=[0, 90, 180, 270],
            help="Rotate input before OCR",
        )
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

    def _ocr_config(self, args: argparse.Namespace, input_is_rgb: bool) -> OcrConfig:
        return OcrConfig(
            lang=args.lang,
            psm=args.psm,
            oem=args.oem,
            rotate=args.rotate,
            scale=args.scale,
            threshold=args.threshold,
            input_is_rgb=input_is_rgb,
        )

    def _cmd_preview(self, args: argparse.Namespace) -> int:
        source = Picamera2Source(width=args.width, height=args.height)
        return source.preview()

    def _cmd_capture_once(self, args: argparse.Namespace) -> int:
        source = Picamera2Source(width=args.width, height=args.height)
        source.start()
        try:
            frame = source.capture_frame()
        finally:
            source.stop()

        frame_path = self._writer.save_frame(frame, "capture_once", input_is_rgb=source.output_is_rgb)
        result = self._ocr.recognize(frame, self._ocr_config(args, input_is_rgb=source.output_is_rgb))
        result_path = self._writer.save_result(result, "capture_once")
        annotated_path = self._writer.save_annotated(result, "capture_once")

        self._print_artifacts(frame_path, result_path, annotated_path)
        self._printer.print_result(result)
        return 0

    def _cmd_capture_interval(self, args: argparse.Namespace) -> int:
        source = Picamera2Source(width=args.width, height=args.height)
        source.start()

        count = 0
        try:
            while args.count is None or count < args.count:
                count += 1
                frame = source.capture_frame()
                name_hint = f"capture_interval_{count:04d}"
                result = self._ocr.recognize(
                    frame,
                    self._ocr_config(args, input_is_rgb=source.output_is_rgb),
                )

                print(f"CAPTURE #{count}")
                if not args.no_save:
                    frame_path = self._writer.save_frame(
                        frame,
                        name_hint,
                        input_is_rgb=source.output_is_rgb,
                    )
                    result_path = self._writer.save_result(result, name_hint)
                    annotated_path = self._writer.save_annotated(result, name_hint)
                    self._print_artifacts(frame_path, result_path, annotated_path)
                self._printer.print_result(result)
                time.sleep(max(args.interval_ms, 0) / 1000.0)
        finally:
            source.stop()

        return 0

    def _cmd_ocr_from_file(self, args: argparse.Namespace) -> int:
        reader = ImageFileReader()
        frame = reader.read(args.image)

        stem = Path(args.image).stem or "input"
        frame_path = self._writer.save_frame(frame, f"ocr_from_file_{stem}", input_is_rgb=reader.output_is_rgb)
        result = self._ocr.recognize(frame, self._ocr_config(args, input_is_rgb=reader.output_is_rgb))
        result_path = self._writer.save_result(result, f"ocr_from_file_{stem}")
        annotated_path = self._writer.save_annotated(result, f"ocr_from_file_{stem}")

        self._print_artifacts(frame_path, result_path, annotated_path)
        self._printer.print_result(result)
        return 0

    @staticmethod
    def _print_artifacts(
        frame_path: Path,
        result_path: Path,
        annotated_path: Optional[Path],
    ) -> None:
        print(f"FRAME_SAVED: {frame_path}")
        print(f"RESULT_SAVED: {result_path}")
        if annotated_path is not None:
            print(f"ANNOTATED_SAVED: {annotated_path}")


def main(argv: Optional[list[str]] = None) -> int:
    return OcrCameraCli().run(argv)
