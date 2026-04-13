"""Gemini vision runner for BatGlass button-driven OCR and scene description."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator
import mimetypes

import cv2
import numpy as np


_DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"


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

        self._client = genai.Client(api_key=resolved_api_key)
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

        saw_output = False
        stream = self._client.models.generate_content_stream(
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
                print("[gemini_vlm] first chunk received")
            yield text

        if not saw_output:
            print("[gemini_vlm] generation finished with no text output")

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

    def _to_image_part(self, source: str | Path | np.ndarray):
        if isinstance(source, np.ndarray):
            ok, encoded = cv2.imencode(".jpg", source)
            if not ok:
                raise RuntimeError("Failed to encode image for Gemini request.")
            data = encoded.tobytes()
            mime_type = "image/jpeg"
        else:
            path = Path(source)
            data = path.read_bytes()
            mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"

        return self._types.Part.from_bytes(data=data, mime_type=mime_type)
