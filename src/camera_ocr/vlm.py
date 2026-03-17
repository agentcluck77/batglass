#!/usr/bin/env python3
"""Optional VLM (vision-language model) OCR via Ollama."""

from __future__ import annotations

from pathlib import Path


def ocr_with_llm(image_path: Path, model: str) -> str:
    """Send an image to an Ollama vision model and return extracted text."""
    try:
        import ollama
    except ImportError as exc:
        raise RuntimeError(
            "Missing optional dependency: ollama. "
            "Install with: uv pip install batglass[vlm]"
        ) from exc

    response = ollama.chat(
        model=model,
        messages=[{
            "role": "user",
            "content": (
                "Extract all visible text from this image exactly as written. "
                "Rejoin hyphenated words that are split across lines. "
                "Output only the extracted text, nothing else."
            ),
            "images": [str(image_path)],
        }],
    )
    return response.message.content.strip()
