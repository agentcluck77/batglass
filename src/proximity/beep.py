#!/usr/bin/env python3
"""Stereo beep output using a persistent aplay process for the WM8960 Audio HAT."""

from __future__ import annotations

import math
import subprocess
import threading
import time
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
        self._pcm_cache: dict[tuple[float, float], bytes] = {}
        self._left_beep_pcm = self._pcm_for_gains(left_gain=1.0, right_gain=0.0)
        self._right_beep_pcm = self._pcm_for_gains(left_gain=0.0, right_gain=1.0)
        self._both_beep_pcm = self._pcm_for_gains(left_gain=1.0, right_gain=1.0)
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

    def beep(
        self,
        *,
        left: bool = False,
        right: bool = False,
        left_gain: float | None = None,
        right_gain: float | None = None,
        silence_after_s: float = 0.0,
    ) -> None:
        """Write one stereo beep plus silence to aplay stdin."""
        if left_gain is not None or right_gain is not None:
            if left_gain is None or right_gain is None:
                raise ValueError("left_gain and right_gain must be provided together")
            data = self._pcm_for_gains(left_gain=left_gain, right_gain=right_gain)
        elif left and right:
            data = self._both_beep_pcm
        elif left:
            data = self._left_beep_pcm
        elif right:
            data = self._right_beep_pcm
        else:
            return

        silence_frames = int(_SAMPLE_RATE * silence_after_s)
        if silence_frames > 0:
            data += bytes(silence_frames * 4)  # 16-bit stereo zeros

        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                with AUDIO_OUTPUT_LOCK:
                    self._proc = self._spawn()
            try:
                self._proc.stdin.write(data)   # type: ignore[union-attr]
                self._proc.stdin.flush()        # type: ignore[union-attr]
            except (BrokenPipeError, OSError):
                detail = _read_process_stderr(self._proc)
                if detail:
                    print(f"[beep] aplay write failed: {detail}")
                self._proc = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _spawn(self) -> subprocess.Popen:
        proc = subprocess.Popen(
            [
                "aplay",
                "-N",
                "-D", self._device,
                "-c", "2",
                "-r", str(_SAMPLE_RATE),
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
            detail = _read_process_stderr(proc)
            if detail:
                print(f"[beep] aplay failed to start: {detail}")
            else:
                print(f"[beep] aplay exited immediately with code {proc.returncode}")
        return proc

    def _pcm_for_gains(self, *, left_gain: float, right_gain: float) -> bytes:
        gains = (_clamp_gain(left_gain), _clamp_gain(right_gain))
        if gains not in self._pcm_cache:
            self._pcm_cache[gains] = _make_beep_pcm(
                left_gain=gains[0],
                right_gain=gains[1],
            )
        return self._pcm_cache[gains]

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


def _read_process_stderr(proc: subprocess.Popen | None) -> str:
    if proc is None or proc.stderr is None:
        return ""
    try:
        return proc.stderr.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _clamp_gain(value: float) -> float:
    return max(0.0, min(1.0, value))


def _make_beep_pcm(*, left_gain: float, right_gain: float) -> bytes:
    frame_count = int(_SAMPLE_RATE * _BEEP_DURATION_S)
    left_amplitude = int(32767 * _BEEP_AMPLITUDE * left_gain)
    right_amplitude = int(32767 * _BEEP_AMPLITUDE * right_gain)
    pcm = bytearray()
    for i in range(frame_count):
        phase = 2.0 * math.pi * _BEEP_FREQUENCY_HZ * (i / _SAMPLE_RATE)
        wave = math.sin(phase)
        left_sample = int(left_amplitude * wave)
        right_sample = int(right_amplitude * wave)
        pcm += left_sample.to_bytes(2, byteorder="little", signed=True)
        pcm += right_sample.to_bytes(2, byteorder="little", signed=True)
    return bytes(pcm)
