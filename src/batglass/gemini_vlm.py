"""Gemini vision runner for BatGlass button-driven OCR and scene description."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator
import mimetypes

import cv2
import numpy as np


_DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"



def _resize_for_gemini(image: np.ndarray, max_px: int) -> np.ndarray:
    h, w = image.shape[:2]
    if max(h, w) <= max_px:
        return image
    scale = max_px / max(h, w)
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

class GeminiVlmRunner:
    """Run Gemini multimodal prompts and yield text chunks."""

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        max_tokens: int = 150,
        temperature: float = 0.1,
    ) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency: google-genai. Install project dependencies with `uv sync`."
            ) from exc

        resolved_api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not resolved_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")

        self._api_keys = [resolved_api_key]
        fallback_key = os.getenv("GEMINI_API_KEY_FALLBACK")
        if fallback_key:
            self._api_keys.append(fallback_key)
        self._genai = genai
        self._client = genai.Client(api_key=self._api_keys[0])
        self._types = types
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def run(
        self,
        image_path: str | Path | np.ndarray,
        prompt: str,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        image_part = self._to_image_part(image_path)
        n = max_tokens or self._max_tokens
        print(f"[gemini_vlm] generate start model={self._model} max_tokens={n}")

        last_exc = None
        for i, key in enumerate(self._api_keys):
            client = self._client if i == 0 else self._genai.Client(api_key=key)
            try:
                saw_output = False
                stream = client.models.generate_content_stream(
                    model=self._model,
                    contents=[image_part, prompt],
                    config={
                        "temperature": self._temperature,
                        "max_output_tokens": n,
                    },
                )
                for chunk in stream:
                    text = getattr(chunk, "text", None)
                    if not text:
                        continue
                    if not saw_output:
                        saw_output = True
                        if i > 0:
                            print(f"[gemini_vlm] using fallback key {i}")
                        print("[gemini_vlm] first chunk received")
                    yield text
                if not saw_output:
                    print("[gemini_vlm] generation finished with no text output")
                return
            except Exception as exc:
                last_exc = exc
                print(f"[gemini_vlm] key {i} failed ({type(exc).__name__}): {exc}")
                if i + 1 < len(self._api_keys):
                    print("[gemini_vlm] retrying with fallback key...")
                continue
        raise last_exc

    def release(self) -> None:
        """Compatibility with older local VLM runners."""

    @staticmethod
    def preprocess_image(source: str | Path | np.ndarray) -> np.ndarray:
        """Return the RGB image that will be sent to Gemini."""
        if isinstance(source, np.ndarray):
            image = source
        else:
            image = cv2.imread(str(source))
            if image is None:
                raise FileNotFoundError(f"Could not read image: {source}")

        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

        if image.ndim == 3 and image.shape[2] == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        raise ValueError(f"Unsupported image shape: {image.shape}")

    # Maximum pixel dimension sent to Gemini — larger images add upload time
    # without improving VLM quality for scene/OCR tasks.
    _GEMINI_MAX_PX = 1024

    def _to_image_part(self, source: str | Path | np.ndarray):
        if isinstance(source, np.ndarray):
            image = source
        else:
            path = Path(source)
            image = cv2.imread(str(path))
            if image is None:
                raise FileNotFoundError(f"Could not read image: {path}")

        image = _resize_for_gemini(image, self._GEMINI_MAX_PX)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError("Failed to encode image for Gemini request.")
        return self._types.Part.from_bytes(data=encoded.tobytes(), mime_type="image/jpeg")
