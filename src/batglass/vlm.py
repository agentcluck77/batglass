"""VLM module — wraps llama-mtmd-cli and streams tokens from stdout.

llama-mtmd-cli writes GGML logs to stderr and generated tokens to stdout.
We capture stdout for the response and discard stderr noise.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Iterator


class VlmRunner:
    """Runs moondream2 (or any llama-mtmd-cli compatible model) and yields tokens.

    Each call spawns a fresh subprocess. The model weights are mmap'd by the OS,
    so after the first call the pages stay warm in the page cache and subsequent
    calls avoid the multi-second cold-load penalty.

    Warm-up: call warm_up() once at startup to prime the page cache.
    """

    def __init__(
        self,
        model: str | Path,
        mmproj: str | Path,
        chat_template: str = "vicuna",
        threads: int = 4,
        temperature: float = 0.1,
    ) -> None:
        self._model = str(Path(model).expanduser())
        self._mmproj = str(Path(mmproj).expanduser())
        self._chat_template = chat_template
        self._threads = threads
        self._temperature = temperature

    def run(
        self,
        image_path: str | Path,
        prompt: str,
        max_tokens: int = 100,
    ) -> Iterator[str]:
        """Yield tokens as they arrive from the model.

        Suitable for piping into TtsSpeaker.speak_stream().
        """
        cmd = [
            "llama-mtmd-cli",
            "-m", self._model,
            "--mmproj", self._mmproj,
            "--chat-template", self._chat_template,
            "--image", str(image_path),
            "-p", prompt,
            "-t", str(self._threads),
            "--temp", str(self._temperature),
            "-n", str(max_tokens),
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        try:
            for token in self._stream_tokens(proc):
                yield token
        finally:
            proc.wait()

    def warm_up(self, image_path: str | Path | None = None) -> None:
        """Prime the OS page cache by running one short inference.

        This pays the mmap cold-start cost once at boot so the first
        real user request isn't delayed by ~3s of page faults.
        """
        # Use a minimal 1×1 JPEG if no image is provided
        img = image_path or self._make_dummy_image()
        t0 = time.perf_counter()
        list(self.run(img, prompt="Hi.", max_tokens=1))
        elapsed = time.perf_counter() - t0
        print(f"[vlm] warm-up done in {elapsed:.1f}s")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _stream_tokens(proc: subprocess.Popen, chunk: int = 256) -> Iterator[str]:
        """Stream generated tokens from stdout.

        llama-mtmd-cli writes the response directly to stdout, cleanly separated
        from the GGML log noise on stderr. We yield the full response as one token.
        """
        buf = b""
        while True:
            data = proc.stdout.read(chunk)
            if not data:
                break
            buf += data

        text = buf.decode("utf-8", errors="replace").strip()
        if text:
            yield text

    @staticmethod
    def _make_dummy_image() -> Path:
        """Write a tiny 1×1 black JPEG to /tmp for warm-up purposes."""
        import cv2
        import numpy as np
        path = Path("/tmp/batglass_warmup.jpg")
        cv2.imwrite(str(path), np.zeros((1, 1, 3), dtype=np.uint8))
        return path
