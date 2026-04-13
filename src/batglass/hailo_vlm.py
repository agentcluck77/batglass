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
        frame = self.preprocess_image(image_path)
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
        print(f"[hailo_vlm] generate start max_tokens={n}")
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
                saw_output = False
                for chunk in generation:
                    if not saw_output:
                        saw_output = True
                        print("[hailo_vlm] first token received")
                    # Strip Qwen end tokens
                    clean = chunk.split("<|im_end|>")[0]
                    if clean:
                        yield clean
                if not saw_output:
                    print("[hailo_vlm] generation finished with no output")
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
    def preprocess_image(source: str | Path | np.ndarray) -> np.ndarray:
        """Load and preprocess image to the exact RGB tensor image sent to the VLM."""
        if isinstance(source, np.ndarray):
            img = source
        else:
            img = cv2.imread(str(source))
            if img is None:
                raise FileNotFoundError(f"Could not read image: {source}")

        # BGR → RGB
        if img.ndim == 3 and img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Crop to the largest centered square so all 336x336 pixels carry image
        # content instead of black letterbox bars. This improves effective detail
        # density for OCR and scene descriptions on 4:3 captures.
        h, w = img.shape[:2]
        side = min(h, w)
        x = max(0, (w - side) // 2)
        y = max(0, (h - side) // 2)
        cropped = img[y:y + side, x:x + side]
        return cv2.resize(
            cropped,
            (_IMAGE_SIZE, _IMAGE_SIZE),
            interpolation=cv2.INTER_LINEAR,
        ).astype(np.uint8)
