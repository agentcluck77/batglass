#!/usr/bin/env python3
"""Audio beep output using a persistent aplay process for the WM8960 Audio HAT.

A single aplay subprocess is kept alive for the duration of an echolocation
session.  Each call to beep() writes one beep tone followed immediately by a
silence pad as a single PCM chunk, so aplay's buffer stays continuously fed
and ALSA underruns (xruns) never occur.
"""

from __future__ import annotations

import math
import subprocess
import threading
from typing import Final

from batglass.audio import AUDIO_OUTPUT_LOCK

_SAMPLE_RATE: Final = 22050
_BEEP_DURATION_S: Final = 0.1
_BEEP_FREQUENCY_HZ: Final = 1000
_BEEP_AMPLITUDE: Final = 0.35

# WM8960 headphone/speaker amplifier registers (numid in ALSA controls).
# The driver blocks I2C writes to these while the PCM stream is active, so
# they must be set *before* aplay opens the device.
_HP_NUMID: Final = 11   # Headphone Playback Volume
_SPK_NUMID: Final = 13  # Speaker Playback Volume
# 109/127 ≈ −12 dB — matches the value in wm8960_asound.state.
HP_SPK_DEFAULT: Final = 109


class Beeper:
    def __init__(
        self,
        device: str = "plughw:wm8960soundcard",
    ) -> None:
        self._device = device
        self._beep_pcm = _make_beep_pcm()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()  # serialises start/beep/close calls

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the persistent aplay process, waiting for any ongoing TTS."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return  # already running
            # Wait for TTS (or any other audio) to finish before claiming the
            # audio device, then hold the lock only long enough to spawn aplay.
            with AUDIO_OUTPUT_LOCK:
                # The WM8960 driver blocks I2C writes to the headphone and
                # speaker amplifier registers while the PCM is streaming.
                # Set them now, while the device is idle.
                _set_wm8960_output_volumes(self._device, HP_SPK_DEFAULT)
                self._proc = self._spawn()

    def close(self) -> None:
        """Terminate the aplay process and release the audio device."""
        with self._lock:
            self._terminate()

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def beep(self, silence_after_s: float) -> None:
        """Write one beep tone + silence_after_s of silence to aplay stdin.

        Writing both together as a single chunk keeps the ALSA buffer
        continuously fed, preventing xruns that would kill the process.
        """
        silence_frames = int(_SAMPLE_RATE * silence_after_s)
        data = self._beep_pcm + bytes(silence_frames * 2)  # 16-bit mono zeros

        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                with AUDIO_OUTPUT_LOCK:
                    self._proc = self._spawn()
            try:
                self._proc.stdin.write(data)   # type: ignore[union-attr]
                self._proc.stdin.flush()        # type: ignore[union-attr]
            except (BrokenPipeError, OSError):
                self._proc = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _spawn(self) -> subprocess.Popen:
        return subprocess.Popen(
            [
                "aplay",
                "-q",
                "-N",
                "-D", self._device,
                "-c", "1",
                "-r", str(_SAMPLE_RATE),
                "-f", "S16_LE",
                "-t", "raw",
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _terminate(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.stdin.close()  # type: ignore[union-attr]
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _set_wm8960_output_volumes(device: str, value: int) -> None:
    """Set headphone and speaker amp volumes while the PCM device is idle.

    Extracts the card name from a device string like 'plughw:wm8960soundcard'
    and uses amixer cset to write both amplifier registers.  Failures are
    intentionally suppressed — a misconfigured volume is better than a crash.
    """
    card = device.split(":", 1)[1] if ":" in device else device
    val_str = f"{value},{value}"
    for numid in (_HP_NUMID, _SPK_NUMID):
        subprocess.run(
            ["amixer", "-c", card, "cset", f"numid={numid}", val_str],
            capture_output=True,
        )


def _make_beep_pcm() -> bytes:
    frame_count = int(_SAMPLE_RATE * _BEEP_DURATION_S)
    amplitude = int(32767 * _BEEP_AMPLITUDE)
    pcm = bytearray()
    for i in range(frame_count):
        phase = 2.0 * math.pi * _BEEP_FREQUENCY_HZ * (i / _SAMPLE_RATE)
        sample = int(amplitude * math.sin(phase))
        pcm += sample.to_bytes(2, byteorder="little", signed=True)
    return bytes(pcm)
