"""TTS module — Piper → aplay streaming pipeline."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Iterator

from batglass.audio import AUDIO_OUTPUT_LOCK


_PIPER_SAMPLE_RATE = 22050
_PROCESS_EXIT_TIMEOUT_S = 30
_APLAY_CHANNELS = 2
_HP_NUMID = 11
_SPK_NUMID = 13
_HP_SPK_DEFAULT = 127


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
                    piper.stdin.flush()
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
        proc = subprocess.Popen(
            [
                "aplay",
                "-N",
                "-D", self._audio_device,
                "-c", str(_APLAY_CHANNELS),
                "-r", str(_PIPER_SAMPLE_RATE),
                "-f", "S16_LE",
                "-t", "raw",
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.05)
        if proc.poll() is not None:
            detail = self._read_process_stderr(proc)
            if detail:
                print(f"[tts] aplay failed to start: {detail}")
            else:
                print(f"[tts] aplay exited immediately with code {proc.returncode}")
        return proc

    def _start_pipeline(self) -> tuple[subprocess.Popen, subprocess.Popen, threading.Thread]:
        piper = self._start_piper()
        _set_wm8960_output_volumes(self._audio_device, _HP_SPK_DEFAULT)
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
        tail = b""
        try:
            while True:
                data = src.read(chunk)
                if not data:
                    break
                stereo, tail = cls._mono_to_stereo(tail + data)
                if stereo:
                    dst.write(stereo)
                dst.flush()
            if tail:
                stereo, _ = cls._mono_to_stereo(tail + b"\x00")
                if stereo:
                    dst.write(stereo)
                    dst.flush()
        except (BrokenPipeError, OSError):
            detail = cls._read_process_stderr(aplay)
            if detail:
                print(f"[tts] aplay write failed: {detail}")
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
        piper_code = cls._wait_for_exit(piper, timeout=_PROCESS_EXIT_TIMEOUT_S)
        pipe_thread.join(timeout=_PROCESS_EXIT_TIMEOUT_S)
        if pipe_thread.is_alive():
            cls._terminate_process(aplay)
            pipe_thread.join(timeout=1)
        aplay_code = cls._wait_for_exit(aplay, timeout=_PROCESS_EXIT_TIMEOUT_S)

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

    @staticmethod
    def _mono_to_stereo(data: bytes) -> tuple[bytes, bytes]:
        """Duplicate 16-bit mono PCM samples into left/right stereo frames."""
        usable = len(data) - (len(data) % 2)
        payload = data[:usable]
        tail = data[usable:]
        if not payload:
            return b"", tail
        stereo = bytearray(len(payload) * 2)
        out = 0
        for i in range(0, len(payload), 2):
            sample = payload[i : i + 2]
            stereo[out : out + 2] = sample
            stereo[out + 2 : out + 4] = sample
            out += 4
        return bytes(stereo), tail


def _set_wm8960_output_volumes(device: str, value: int) -> None:
    """Enable WM8960 headphone/speaker amps before playback starts."""
    card = device.split(":", 1)[1] if ":" in device else device
    val_str = f"{value},{value}"
    for numid in (_HP_NUMID, _SPK_NUMID):
        subprocess.run(
            ["amixer", "-c", card, "cset", f"numid={numid}", val_str],
            capture_output=True,
        )
