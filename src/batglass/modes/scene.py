"""Scene mode — hold button, ask a question, get spoken description."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from camera_ocr.camera import to_bgr

if TYPE_CHECKING:
    from batglass.stt import SttRunner
    from batglass.tts import TtsSpeaker
    from batglass.vlm import VlmRunner

_IMAGE_PATH = Path("/tmp/batglass_scene_frame.jpg")
_DEFAULT_PROMPT = "Describe what you see in this image."


class SceneMode:
    """Capture image + transcribe speech in parallel, then speak VLM response.

    Timeline (parallel capture)::

        t=0       button released
        t=0..Xs   [thread A] capture frame → save JPEG
        t=0..Ys   [thread B] transcribe question via whisper-cli
        t=max(X,Y) VLM run → streaming TTS
    """

    def __init__(
        self,
        stt: SttRunner,
        vlm: VlmRunner,
        tts: TtsSpeaker,
        camera,
        record_duration_s: float = 5.0,
    ) -> None:
        self._stt = stt
        self._vlm = vlm
        self._tts = tts
        self._camera = camera
        self._record_duration_s = record_duration_s

    def run(self) -> None:
        """Capture image and transcribe speech concurrently, then describe."""
        image_path_holder: list[Path] = []
        transcript_holder: list[str] = []
        errors: list[Exception] = []

        def capture_image() -> None:
            try:
                import cv2
                frame = self._camera.capture_frame()
                frame_bgr = to_bgr(
                    frame,
                    input_is_rgb=getattr(self._camera, "output_is_rgb", False),
                )
                cv2.imwrite(str(_IMAGE_PATH), frame_bgr)
                image_path_holder.append(_IMAGE_PATH)
            except Exception as e:
                errors.append(e)

        def transcribe_question() -> None:
            try:
                text = self._stt.record_and_transcribe(self._record_duration_s)
                transcript_holder.append(text)
            except Exception as e:
                errors.append(e)

        t_capture = threading.Thread(target=capture_image, daemon=True)
        t_stt = threading.Thread(target=transcribe_question, daemon=True)
        t_capture.start()
        t_stt.start()
        t_capture.join()
        t_stt.join()

        if errors:
            self._tts.speak("Sorry, I had an error capturing the scene.")
            return

        image_path = image_path_holder[0] if image_path_holder else None
        question = transcript_holder[0] if transcript_holder else ""

        if image_path is None:
            self._tts.speak("Sorry, I could not capture an image.")
            return

        prompt = question.strip() if question.strip() else _DEFAULT_PROMPT
        print(f"[scene] question={repr(prompt)}")

        tokens = self._vlm.run(
            image_path=image_path,
            prompt=prompt,
            max_tokens=150,
        )
        self._tts.speak_stream(tokens)
