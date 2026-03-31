"""Shared coordination for ALSA audio playback."""

from __future__ import annotations

import threading


# All playback on the WM8960 card should be serialized. ALSA `hw:*`
# devices are exclusive, so concurrent `aplay` instances can fail.
AUDIO_OUTPUT_LOCK = threading.RLock()
