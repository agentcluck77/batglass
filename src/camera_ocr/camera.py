#!/usr/bin/env python3
"""Camera layer for OCR CLI."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Protocol

try:
    import cv2
except ImportError:  # pragma: no cover - runtime dependency check
    cv2 = None

try:
    from picamera2 import Picamera2
except ImportError:  # pragma: no cover - runtime dependency check
    Picamera2 = None


class CameraSource(Protocol):
    output_is_rgb: bool

    def start(self) -> None:
        ...

    def capture_frame(self):
        ...

    def stop(self) -> None:
        ...

    def preview(self) -> int:
        ...


class Picamera2Source:
    output_is_rgb = True

    def __init__(
        self,
        width: int,
        height: int,
        warmup_seconds: float = 1.0,
        autofocus_enabled: bool = True,
    ):
        self._width = width
        self._height = height
        self._warmup_seconds = warmup_seconds
        self._autofocus_enabled = autofocus_enabled
        self._autofocus_available = False
        self._picam2 = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        if Picamera2 is None:
            raise RuntimeError("Missing dependency: picamera2. Install via apt.")
        try:
            self._picam2 = Picamera2()
            config = self._picam2.create_still_configuration(
                main={"size": (self._width, self._height)}
            )
            self._picam2.configure(config)
            self._picam2.start()
            time.sleep(self._warmup_seconds)
            self._started = True
            self._autofocus_available = self._detect_autofocus()
            if self._autofocus_available:
                self._run_autofocus_cycle(reason="startup")
        except IndexError as exc:
            self._safe_close()
            raise RuntimeError(
                "No usable camera was registered by libcamera. "
                "For Arducam 64MP, verify the tuning file exists at "
                "/usr/share/libcamera/ipa/rpi/pisp/arducam_64mp.json."
            ) from exc
        except Exception as exc:
            self._safe_close()
            raise RuntimeError(f"Failed to initialize camera: {exc}") from exc

    def capture_frame(self):
        return self._capture_frame(autofocus=True)

    def _capture_frame(self, autofocus: bool):
        if not self._started or self._picam2 is None:
            raise RuntimeError("Camera is not started")
        if autofocus and self._autofocus_available:
            self._run_autofocus_cycle(reason="capture")
        return self._picam2.capture_array("main")

    def stop(self) -> None:
        if not self._started or self._picam2 is None:
            return

        self._picam2.stop()
        self._picam2.close()
        self._picam2 = None
        self._autofocus_available = False
        self._started = False

    def _safe_close(self) -> None:
        if self._picam2 is None:
            return
        try:
            self._picam2.close()
        except Exception:
            pass
        self._picam2 = None
        self._autofocus_available = False
        self._started = False

    def _detect_autofocus(self) -> bool:
        if not self._autofocus_enabled or self._picam2 is None:
            return False

        camera_controls = getattr(self._picam2, "camera_controls", {})
        if "AfMode" not in camera_controls or not hasattr(self._picam2, "autofocus_cycle"):
            print("[camera] autofocus not supported; using fixed-focus capture")
            return False
        return True

    def _run_autofocus_cycle(self, reason: str) -> None:
        if self._picam2 is None:
            return

        try:
            ok = bool(self._picam2.autofocus_cycle(wait=True))
        except Exception as exc:
            print(f"[camera] autofocus {reason} failed ({exc})")
            self._autofocus_available = False
            return

        if reason != "startup" and ok:
            return

        metadata = self._picam2.capture_metadata()
        print(
            f"[camera] autofocus {reason}: "
            f"ok={ok} state={metadata.get('AfState')} lens={metadata.get('LensPosition')}"
        )

    def preview(self) -> int:
        if cv2 is None:
            raise RuntimeError("Missing dependency: opencv-python. Install with uv.")
        if not _has_graphical_display():
            raise RuntimeError(
                "Preview requires a graphical display (DISPLAY/WAYLAND_DISPLAY). "
                "Use capture-once or capture-interval in headless sessions."
            )

        self.start()
        try:
            while True:
                frame = self._capture_frame(autofocus=False)
                display = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                cv2.imshow("OCR Camera Preview (q to quit)", display)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    return 0
        finally:
            cv2.destroyAllWindows()
            self.stop()


class ImageFileReader:
    output_is_rgb = False

    def read(self, path: str):
        if cv2 is None:
            raise RuntimeError("Missing dependency: opencv-python. Install with uv.")

        image = cv2.imread(str(Path(path)))
        if image is None:
            raise FileNotFoundError(f"Unable to read image: {path}")
        return image


def to_bgr(frame: Any, input_is_rgb: bool):
    if cv2 is None:
        raise RuntimeError("Missing dependency: opencv-python. Install with uv.")
    if input_is_rgb:
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    return frame


def _has_graphical_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
