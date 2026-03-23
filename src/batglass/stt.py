"""STT module — wraps whisper-cli for speech-to-text.

Records audio via arecord, then transcribes with whisper-cli.
whisper-cli writes transcription to stdout (one segment per line).

Two recording modes:
  - Fixed duration: record_and_transcribe(duration_s)
  - Hold-to-record: start_recording() ... stop_and_transcribe()
    arecord runs open-ended (max 30s cap); stop_and_transcribe() sends
    SIGTERM to flush and close the WAV, then runs whisper-cli.
"""

from __future__ import annotations

import signal
import subprocess
import tempfile
from pathlib import Path


_WHISPER_SAMPLE_RATE = 16000
_MAX_HOLD_DURATION_S = 30


class SttRunner:
    """Record microphone audio and transcribe with whisper.cpp."""

    def __init__(
        self,
        model: str | Path,
        audio_device: str = "hw:wm8960soundcard",
        threads: int = 4,
    ) -> None:
        self._model = str(Path(model).expanduser())
        self._audio_device = audio_device
        self._threads = threads
        self._rec_proc: subprocess.Popen | None = None
        self._rec_wav: str | None = None

    # ------------------------------------------------------------------
    # Hold-to-record API (scene button)
    # ------------------------------------------------------------------

    def start_recording(self) -> None:
        """Start recording immediately (non-blocking).

        Call stop_and_transcribe() when the button is released.
        Capped at _MAX_HOLD_DURATION_S to prevent runaway recordings.
        """
        f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self._rec_wav = f.name
        f.close()

        self._rec_proc = subprocess.Popen(
            [
                "arecord",
                "-D", self._audio_device,
                "-f", "S16_LE",
                "-r", str(_WHISPER_SAMPLE_RATE),
                "-c", "1",
                "-d", str(_MAX_HOLD_DURATION_S),
                self._rec_wav,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_and_transcribe(self) -> str:
        """Stop recording (SIGTERM flushes the WAV) and return transcript."""
        if self._rec_proc is None or self._rec_wav is None:
            return ""
        proc, wav = self._rec_proc, self._rec_wav
        self._rec_proc = None
        self._rec_wav = None

        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=3)
        except Exception:
            proc.kill()

        try:
            return self._transcribe(wav)
        finally:
            Path(wav).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Fixed-duration API (fallback / direct use)
    # ------------------------------------------------------------------

    def record_and_transcribe(self, duration_s: float = 5.0) -> str:
        """Record *duration_s* seconds of audio and return transcribed text."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name

        try:
            subprocess.run(
                [
                    "arecord",
                    "-D", self._audio_device,
                    "-f", "S16_LE",
                    "-r", str(_WHISPER_SAMPLE_RATE),
                    "-c", "1",
                    "-d", str(int(duration_s)),
                    wav_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return self._transcribe(wav_path)
        finally:
            Path(wav_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _transcribe(self, wav_path: str) -> str:
        """Run whisper-cli on *wav_path* and return the transcript."""
        result = subprocess.run(
            [
                "whisper-cli",
                "-m", self._model,
                "-t", str(self._threads),
                "-l", "en",
                "--no-timestamps",
                "-f", wav_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        lines = result.stdout.decode("utf-8", errors="replace").splitlines()
        return " ".join(line.strip() for line in lines if line.strip())
