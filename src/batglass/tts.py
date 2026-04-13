"""TTS module — espeak-ng → aplay pipeline."""

from __future__ import annotations

import subprocess
from typing import Iterator

from batglass.audio import AUDIO_OUTPUT_LOCK


_HP_NUMID = 11
_SPK_NUMID = 13
_OUT_LEFT_NUMID = 52
_OUT_RIGHT_NUMID = 55
_HP_SPK_DEFAULT = 127


class TtsSpeaker:
    """Synthesise and play speech via espeak-ng → aplay.

    All public methods block until audio finishes playing.
    The model parameter is accepted for API compatibility but unused.
    """

    def __init__(
        self,
        model: str | None = None,
        audio_device: str = "plughw:wm8960soundcard",
    ) -> None:
        self._audio_device = audio_device

    def speak(self, text: str) -> None:
        """Synthesise and play a complete text string."""
        if not text.strip():
            return
        with AUDIO_OUTPUT_LOCK:
            _set_wm8960_output_volumes(self._audio_device, _HP_SPK_DEFAULT)
            espeak = subprocess.run(
                ["espeak-ng", "--stdout", "-v", "en-us", "-s", "150", text],
                capture_output=True,
            )
            if espeak.returncode != 0:
                print(f"[tts] espeak-ng failed with code {espeak.returncode}")
                return
            aplay = subprocess.Popen(
                ["aplay", "-N", "-D", self._audio_device],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _, stderr = aplay.communicate(input=espeak.stdout)
            if aplay.returncode not in (0, None):
                detail = stderr.decode(errors="replace").strip()
                print(f"[tts] aplay failed: {detail or aplay.returncode}")

    def speak_stream(self, token_iter: Iterator[str]) -> None:
        """Collect streamed tokens then speak once (espeak-ng is near-instant)."""
        text = "".join(token_iter).strip()
        if text:
            self.speak(text)


def _set_wm8960_output_volumes(device: str, value: int) -> None:
    card = device.split(':', 1)[1] if ':' in device else device
    val_str = f'{value},{value}'
    for numid in (_HP_NUMID, _SPK_NUMID):
        subprocess.run(['amixer', '-c', card, 'cset', f'numid={numid}', val_str], capture_output=True)
    for numid in (_OUT_LEFT_NUMID, _OUT_RIGHT_NUMID):
        subprocess.run(['amixer', '-c', card, 'cset', f'numid={numid}', 'on'], capture_output=True)
