"""Gemini Live API runner — image + prompt → streamed audio output.

Replaces the GeminiVlmRunner + TtsSpeaker pipeline with a single call that
sends a JPEG image to the Live API and streams the synthesised audio response
directly to the WM8960 via aplay.

Output audio spec: raw 16-bit PCM, 24 kHz, mono, little-endian.
We duplicate each sample to stereo before feeding aplay.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from pathlib import Path
from typing import AsyncIterator

import cv2
import numpy as np

from batglass.audio import AUDIO_OUTPUT_LOCK

_LIVE_SAMPLE_RATE = 24000   # Hz — Gemini Live output spec
_LIVE_MODEL = "gemini-2.0-flash-live-001"
_HP_NUMID = 11
_SPK_NUMID = 13
_OUT_LEFT_NUMID = 52
_OUT_RIGHT_NUMID = 55
_HP_SPK_DEFAULT = 127
_GEMINI_MAX_PX = 1024


class GeminiLiveRunner:
    """Send image + prompt to Gemini Live API and play the audio response."""

    def __init__(
        self,
        model: str = _LIVE_MODEL,
        api_key: str | None = None,
        audio_device: str = "plughw:wm8960soundcard",
    ) -> None:
        from google import genai
        self._genai = genai
        self._api_keys = [api_key or os.getenv("GEMINI_API_KEY", "")]
        fallback = os.getenv("GEMINI_API_KEY_FALLBACK")
        if fallback:
            self._api_keys.append(fallback)
        self._model = model
        self._audio_device = audio_device

    def speak_image(self, image_path: str | Path | np.ndarray, prompt: str) -> None:
        """Run inference on image and stream audio response to speaker.

        Blocks until audio playback is complete.
        """
        jpeg_bytes = _load_and_encode(image_path, _GEMINI_MAX_PX)

        last_exc = None
        for i, key in enumerate(self._api_keys):
            try:
                with AUDIO_OUTPUT_LOCK:
                    _set_wm8960_output_volumes(self._audio_device, _HP_SPK_DEFAULT)
                    aplay = subprocess.Popen(
                        ["aplay", "-N", "-D", self._audio_device,
                         "-c", "2", "-r", str(_LIVE_SAMPLE_RATE), "-f", "S16_LE", "-t", "raw", "-"],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    try:
                        asyncio.run(
                            self._stream_audio(key, jpeg_bytes, prompt, aplay.stdin)
                        )
                    finally:
                        try:
                            aplay.stdin.close()
                        except OSError:
                            pass
                        aplay.wait(timeout=10)
                if i > 0:
                    print(f"[gemini_live] used fallback key {i}")
                return
            except Exception as exc:
                last_exc = exc
                print(f"[gemini_live] key {i} failed ({type(exc).__name__}): {exc}")
                if i + 1 < len(self._api_keys):
                    print("[gemini_live] retrying with fallback key...")
        raise last_exc

    async def _stream_audio(
        self,
        api_key: str,
        jpeg_bytes: bytes,
        prompt: str,
        aplay_stdin,
    ) -> None:
        from google.genai import types

        client = self._genai.Client(api_key=api_key)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
        )

        print(f"[gemini_live] connecting model={self._model}")
        async with client.aio.live.connect(model=self._model, config=config) as session:
            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                data=jpeg_bytes,
                                mime_type="image/jpeg",
                            )
                        ),
                        types.Part(text=prompt),
                    ],
                ),
                turn_complete=True,
            )
            print("[gemini_live] waiting for audio...")
            first = True
            async for response in session.receive():
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            if first:
                                print("[gemini_live] first audio chunk received")
                                first = False
                            stereo = _mono_to_stereo(part.inline_data.data)
                            try:
                                aplay_stdin.write(stereo)
                                aplay_stdin.flush()
                            except (BrokenPipeError, OSError):
                                return
                if response.server_content and response.server_content.turn_complete:
                    print("[gemini_live] turn complete")
                    break

    def release(self) -> None:
        pass


def _load_and_encode(source: str | Path | np.ndarray, max_px: int) -> bytes:
    if isinstance(source, np.ndarray):
        image = source
    else:
        image = cv2.imread(str(source))
        if image is None:
            raise FileNotFoundError(f"Could not read image: {source}")
    h, w = image.shape[:2]
    if max(h, w) > max_px:
        scale = max_px / max(h, w)
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("Failed to encode image")
    return encoded.tobytes()


def _mono_to_stereo(data: bytes) -> bytes:
    usable = len(data) - (len(data) % 2)
    payload = data[:usable]
    stereo = bytearray(len(payload) * 2)
    out = 0
    for i in range(0, len(payload), 2):
        stereo[out:out + 2] = payload[i:i + 2]
        stereo[out + 2:out + 4] = payload[i:i + 2]
        out += 4
    return bytes(stereo)


def _set_wm8960_output_volumes(device: str, value: int) -> None:
    card = device.split(":", 1)[1] if ":" in device else device
    val_str = f"{value},{value}"
    for numid in (_HP_NUMID, _SPK_NUMID):
        subprocess.run(["amixer", "-c", card, "cset", f"numid={numid}", val_str], capture_output=True)
    for numid in (_OUT_LEFT_NUMID, _OUT_RIGHT_NUMID):
        subprocess.run(["amixer", "-c", card, "cset", f"numid={numid}", "on"], capture_output=True)
