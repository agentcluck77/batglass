"""TTS module — Piper (or espeak-ng fallback) -> aplay pipeline."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from typing import Iterator

from batglass.audio import AUDIO_OUTPUT_LOCK


_SAMPLE_RATE = 22050
_HP_NUMID = 11
_SPK_NUMID = 13
_OUT_LEFT_NUMID = 52
_OUT_RIGHT_NUMID = 55
_HP_SPK_DEFAULT = 127


class TtsSpeaker:
    def __init__(
        self,
        model: str | Path | None = None,
        audio_device: str = "plughw:wm8960soundcard",
    ) -> None:
        self._model = str(Path(model).expanduser()) if model else None
        self._audio_device = audio_device
        self._piper_bin = (
            shutil.which("piper")
            or str(Path(__file__).resolve().parents[2] / ".venv/bin/piper")
        )

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        with AUDIO_OUTPUT_LOCK:
            _set_wm8960_output_volumes(self._audio_device, _HP_SPK_DEFAULT)
            self._speak_espeak(text)

    def speak_stream(self, token_iter) -> None:
        text = "".join(token_iter).strip()
        if text:
            self.speak(text)

    def _speak_piper(self, text: str) -> None:
        piper = subprocess.Popen(
            [self._piper_bin, "--model", self._model, "--output-raw", "--length-scale", "1.3"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        aplay = subprocess.Popen(
            ["aplay", "-N", "-D", self._audio_device,
             "-c", "2", "-r", str(_SAMPLE_RATE), "-f", "S16_LE", "-t", "raw", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        pipe_thread = threading.Thread(
            target=_pipe_mono_to_stereo, args=(piper.stdout, aplay.stdin), daemon=True
        )
        pipe_thread.start()
        try:
            piper.stdin.write(text.encode())
        except BrokenPipeError:
            pass
        finally:
            try:
                piper.stdin.close()
            except OSError:
                pass
        piper.wait()
        pipe_thread.join(timeout=30)
        try:
            aplay.stdin.close()
        except OSError:
            pass
        aplay.wait(timeout=30)
        if aplay.returncode not in (0, None):
            detail = aplay.stderr.read().decode(errors="replace").strip()
            if detail:
                print(f"[tts] aplay failed: {detail}")

    def _speak_espeak(self, text: str) -> None:
        espeak = subprocess.run(
            ["espeak-ng", "--stdout", "-v", "en-us", "-s", "150", text],
            capture_output=True,
        )
        if espeak.returncode != 0:
            print(f"[tts] espeak-ng failed: {espeak.returncode}")
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


def _pipe_mono_to_stereo(src, dst, chunk: int = 4096) -> None:
    """Copy 16-bit mono PCM from src to dst, duplicating each sample to L+R."""
    tail = b""
    try:
        while True:
            data = src.read(chunk)
            if not data:
                break
            combined = tail + data
            usable = len(combined) - (len(combined) % 2)
            tail = combined[usable:]
            payload = combined[:usable]
            if not payload:
                continue
            stereo = bytearray(len(payload) * 2)
            out = 0
            for i in range(0, len(payload), 2):
                sample = payload[i:i + 2]
                stereo[out:out + 2] = sample
                stereo[out + 2:out + 4] = sample
                out += 4
            dst.write(bytes(stereo))
            dst.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            dst.close()
        except OSError:
            pass


def _set_wm8960_output_volumes(device: str, value: int) -> None:
    card = device.split(":", 1)[1] if ":" in device else device
    val_str = f"{value},{value}"
    for numid in (_HP_NUMID, _SPK_NUMID):
        subprocess.run(["amixer", "-c", card, "cset", f"numid={numid}", val_str], capture_output=True)
    for numid in (_OUT_LEFT_NUMID, _OUT_RIGHT_NUMID):
        subprocess.run(["amixer", "-c", card, "cset", f"numid={numid}", "on"], capture_output=True)
