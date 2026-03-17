"""TTS module — Piper → aplay streaming pipeline."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Iterator


_PIPER_SAMPLE_RATE = 22050


class TtsSpeaker:
    """Synthesise and play speech via Piper TTS → aplay.

    All public methods block until audio finishes playing.
    """

    def __init__(
        self,
        model: str | Path,
        audio_device: str = "hw:wm8960soundcard",
    ) -> None:
        self._model = str(Path(model).expanduser())
        self._audio_device = audio_device

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """Synthesise and play a complete text string."""
        if not text.strip():
            return
        piper = self._start_piper()
        aplay = self._start_aplay()
        try:
            piper.stdin.write(text.encode())
            piper.stdin.close()
            self._pipe(piper.stdout, aplay.stdin)
            aplay.stdin.close()
        finally:
            piper.wait()
            aplay.wait()

    def speak_stream(self, token_iter: Iterator[str]) -> None:
        """Play a stream of tokens, speaking sentence by sentence.

        Starts audio after the first sentence boundary so TTS overlaps
        VLM generation — the user hears the first sentence while the
        VLM is still producing the second.
        """
        piper = self._start_piper()
        aplay = self._start_aplay()

        pipe_thread = threading.Thread(
            target=self._pipe, args=(piper.stdout, aplay.stdin), daemon=True
        )
        pipe_thread.start()

        buf: list[str] = []
        try:
            for token in token_iter:
                buf.append(token)
                if any(c in token for c in ".!?\n"):
                    sentence = "".join(buf).strip()
                    buf.clear()
                    if sentence:
                        piper.stdin.write((sentence + " ").encode())
                        piper.stdin.flush()
            # flush any remaining partial sentence
            remainder = "".join(buf).strip()
            if remainder:
                piper.stdin.write(remainder.encode())
            piper.stdin.close()
        except BrokenPipeError:
            pass
        finally:
            pipe_thread.join()
            aplay.stdin.close()
            piper.wait()
            aplay.wait()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _start_piper(self) -> subprocess.Popen:
        return subprocess.Popen(
            [
                "piper",
                "--model", self._model,
                "--output-raw",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def _start_aplay(self) -> subprocess.Popen:
        return subprocess.Popen(
            [
                "aplay",
                "-D", self._audio_device,
                "-r", str(_PIPER_SAMPLE_RATE),
                "-f", "S16_LE",
                "-t", "raw",
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @staticmethod
    def _pipe(src, dst, chunk: int = 4096) -> None:
        """Copy bytes from src to dst until EOF."""
        try:
            while True:
                data = src.read(chunk)
                if not data:
                    break
                dst.write(data)
                dst.flush()
        except (BrokenPipeError, OSError):
            pass
