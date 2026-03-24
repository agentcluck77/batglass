#!/usr/bin/env python3
"""Audio beep output using sox + aplay for the WM8960 Audio HAT."""

from __future__ import annotations

import subprocess


class Beeper:
    def __init__(self, device: str = "hw:2,0", wav_path: str = "/tmp/beep.wav"):
        self._device = device
        self._wav_path = wav_path
        self._prepare()

    def _prepare(self) -> None:
        """Pre-generate a short beep WAV file."""
        subprocess.run(
            [
                "sox", "-n", "-r", "48000", "-c", "2", self._wav_path,
                "synth", "0.1", "sine", "1000",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def beep(self) -> None:
        subprocess.run(
            ["aplay", "-D", self._device, self._wav_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
