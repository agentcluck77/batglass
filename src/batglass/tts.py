"""TTS module — Piper → aplay streaming pipeline."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Iterator

from batglass.audio import AUDIO_OUTPUT_LOCK


_PIPER_SAMPLE_RATE = 22050


class TtsSpeaker:
    """Synthesise and play speech via Piper TTS → aplay.

    All public methods block until audio finishes playing.
    """

    def __init__(
        self,
        model: str | Path,
        audio_device: str = "plughw:wm8960soundcard",
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
        with AUDIO_OUTPUT_LOCK:
            piper, aplay, pipe_thread = self._start_pipeline()
            try:
                piper.stdin.write(text.encode())
            except BrokenPipeError:
                pass
            finally:
                self._close_pipe(piper.stdin)
                self._finish_pipeline(piper, aplay, pipe_thread)

    def speak_stream(self, token_iter: Iterator[str]) -> None:
        """Play a stream of tokens, speaking sentence by sentence.

        Starts audio after the first sentence boundary so TTS overlaps
        VLM generation — the user hears the first sentence while the
        VLM is still producing the second.
        """
        with AUDIO_OUTPUT_LOCK:
            piper, aplay, pipe_thread = self._start_pipeline()

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
                remainder = "".join(buf).strip()
                if remainder:
                    piper.stdin.write(remainder.encode())
            except BrokenPipeError:
                pass
            finally:
                self._close_pipe(piper.stdin)
                self._finish_pipeline(piper, aplay, pipe_thread)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _start_piper(self) -> subprocess.Popen:
        import shutil
        piper_bin = shutil.which("piper") or str(
            Path(__file__).resolve().parents[2] / ".venv/bin/piper"
        )
        return subprocess.Popen(
            [
                piper_bin,
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
                "-N",
                "-D", self._audio_device,
                "-c", "1",
                "-r", str(_PIPER_SAMPLE_RATE),
                "-f", "S16_LE",
                "-t", "raw",
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def _start_pipeline(self) -> tuple[subprocess.Popen, subprocess.Popen, threading.Thread]:
        piper = self._start_piper()
        aplay = self._start_aplay()
        pipe_thread = threading.Thread(
            target=self._pipe,
            args=(piper, aplay),
            daemon=True,
        )
        pipe_thread.start()
        return piper, aplay, pipe_thread

    @classmethod
    def _pipe(cls, piper: subprocess.Popen, aplay: subprocess.Popen, chunk: int = 4096) -> None:
        """Copy bytes from Piper to aplay until EOF or sink failure."""
        src = piper.stdout
        dst = aplay.stdin
        try:
            while True:
                data = src.read(chunk)
                if not data:
                    break
                dst.write(data)
                dst.flush()
        except (BrokenPipeError, OSError):
            cls._terminate_process(piper)
        finally:
            cls._close_pipe(dst)

    @classmethod
    def _finish_pipeline(
        cls,
        piper: subprocess.Popen,
        aplay: subprocess.Popen,
        pipe_thread: threading.Thread,
    ) -> None:
        pipe_thread.join(timeout=5)
        if pipe_thread.is_alive():
            cls._terminate_process(piper)
            pipe_thread.join(timeout=1)

        piper_code = cls._wait_for_exit(piper)
        aplay_code = cls._wait_for_exit(aplay)

        if aplay_code not in (0, None):
            detail = cls._read_process_stderr(aplay)
            if detail:
                print(f"[tts] aplay failed: {detail}")
            else:
                print(f"[tts] aplay exited with code {aplay_code}")

        if piper_code not in (0, None) and aplay_code in (0, None):
            print(f"[tts] piper exited with code {piper_code}")

    @staticmethod
    def _wait_for_exit(proc: subprocess.Popen, timeout: float = 5) -> int | None:
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                return proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                return None

    @staticmethod
    def _terminate_process(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            return

    @staticmethod
    def _close_pipe(pipe) -> None:
        if pipe is None:
            return
        try:
            pipe.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    @staticmethod
    def _read_process_stderr(proc: subprocess.Popen) -> str:
        if proc.stderr is None:
            return ""
        try:
            return proc.stderr.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return ""
