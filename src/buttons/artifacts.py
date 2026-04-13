from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PHOTOS_DIR = PROJECT_ROOT / "photos"


def save_button_frame(frame_bgr, category: str, name_hint: str) -> Path:
    output_dir = PHOTOS_DIR / category
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = output_dir / f"{ts}_{name_hint}.jpg"
    ok = cv2.imwrite(str(path), frame_bgr)
    if not ok:
        raise RuntimeError(f"Failed to save frame to {path}")
    return path


def save_button_artifact(image_bgr, category: str, name_hint: str) -> Path:
    output_dir = PHOTOS_DIR / category
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = output_dir / f"{ts}_{name_hint}.jpg"
    ok = cv2.imwrite(str(path), image_bgr)
    if not ok:
        raise RuntimeError(f"Failed to save frame to {path}")
    return path


def save_upscaled_artifact(
    image_bgr,
    category: str,
    name_hint: str,
    scale: int = 4,
) -> Path:
    enlarged = cv2.resize(
        image_bgr,
        (image_bgr.shape[1] * scale, image_bgr.shape[0] * scale),
        interpolation=cv2.INTER_NEAREST,
    )
    return save_button_artifact(enlarged, category, name_hint)
