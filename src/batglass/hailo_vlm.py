"""Hailo-10H VLM runner — wraps hailo_platform.genai.VLM (Qwen2-VL-2B-Instruct).

Drop-in replacement for VlmRunner when the Hailo-10H is available.
The model is auto-downloaded on first use from Hailo's GenAI Model Zoo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

# hailo-apps repo must be on PYTHONPATH for resolve_hef_path
_HAILO_APPS = Path(__file__).resolve().parents[3] / "reference/hailo-apps"
if str(_HAILO_APPS) not in sys.path:
    sys.path.insert(0, str(_HAILO_APPS))

_IMAGE_SIZE = 336  # Qwen2-VL-2B-Instruct input resolution

_SYSTEM_PROMPT = "You are a helpful assistant integrated into smart glasses. Be concise."


class HailoVlmRunner:
    """Run Qwen2-VL-2B-Instruct on the Hailo-10H and yield response tokens.

    Usage::

        runner = HailoVlmRunner()          # loads model once
        for token in runner.run(frame, "What do you see?"):
            print(token, end="", flush=True)
    """

    def __init__(
        self,
        hef_path: str | Path | None = None,
        max_tokens: int = 150,
        temperature: float = 0.1,
        seed: int = 42,
    ) -> None:
        from hailo_platform import VDevice
        from hailo_platform.genai import VLM
        from hailo_apps.python.core.common.core import resolve_hef_path
        from hailo_apps.python.core.common.defines import (
            VLM_CHAT_APP, SHARED_VDEVICE_GROUP_ID, HAILO10H_ARCH
        )

        self._max_tokens = max_tokens
        self._temperature = temperature
        self._seed = seed

        resolved = hef_path or resolve_hef_path(None, app_name=VLM_CHAT_APP, arch=HAILO10H_ARCH)
        if resolved is None:
            raise RuntimeError("Could not resolve Hailo VLM HEF path — download may have failed.")

        print(f"[hailo_vlm] loading {resolved}")
        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        self._vdevice = VDevice(params)
        self._vlm = VLM(self._vdevice, str(resolved))
        print("[hailo_vlm] model ready")

    def run(
        self,
        image_path: str | Path | np.ndarray,
        prompt: str,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """Yield response tokens for the given image and prompt.

        *image_path* can be a file path or a numpy BGR frame from OpenCV.
        """
        frame = self._load_image(image_path)
        messages = [
            {
                "role": "system",
                "content": [{"type": "text", "text": _SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": prompt},
                ],
            },
        ]

        n = max_tokens or self._max_tokens
        # Clear any leftover context from a previous call before starting
        try:
            self._vlm.clear_context()
        except Exception:
            pass
        try:
            with self._vlm.generate(
                prompt=messages,
                frames=[frame],
                temperature=self._temperature,
                seed=self._seed,
                max_generated_tokens=n,
            ) as generation:
                for chunk in generation:
                    # Strip Qwen end tokens
                    clean = chunk.split("<|im_end|>")[0]
                    if clean:
                        yield clean
        finally:
            self._vlm.clear_context()

    def release(self) -> None:
        """Free Hailo device resources."""
        try:
            self._vlm.release()
            self._vdevice.release()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _load_image(source: str | Path | np.ndarray) -> np.ndarray:
        """Load and preprocess image to 336×336 RGB."""
        if isinstance(source, np.ndarray):
            img = source
        else:
            img = cv2.imread(str(source))
            if img is None:
                raise FileNotFoundError(f"Could not read image: {source}")

        # BGR → RGB
        if img.ndim == 3 and img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Scale to cover 336×336 then centre-crop
        h, w = img.shape[:2]
        scale = max(_IMAGE_SIZE / w, _IMAGE_SIZE / h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        x = (new_w - _IMAGE_SIZE) // 2
        y = (new_h - _IMAGE_SIZE) // 2
        return img[y:y + _IMAGE_SIZE, x:x + _IMAGE_SIZE].astype(np.uint8)
