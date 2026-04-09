#!/usr/bin/env python3
"""GPIO 5 / 6 — adjust WM8960 speaker volume."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import lgpio

from proximity.beep import Beeper

# -- config -------------------------------------------------------------------
VOLUME_UP_PIN = 5
VOLUME_DOWN_PIN = 6
MIXER_CARD_NAME = "wm8960soundcard"
# `Playback` is the stable master output control on this WM8960 setup.
MIXER_CONTROL = "Playback"
VOLUME_STEP_DB = 2
PLAYBACK_DB_PER_RAW_STEP = 0.5
VOLUME_STEP_RAW = int(round(VOLUME_STEP_DB / PLAYBACK_DB_PER_RAW_STEP))
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class MixerLevel:
    raw: int
    raw_min: int
    raw_max: int
    percent: int | None
    db: float | None


class VolumeButton:
    def __init__(
        self,
        pin: int,
        delta_db: int,
        chip: int = 0,
        feedback_beeper: Beeper | None = None,
    ) -> None:
        if delta_db == 0:
            raise ValueError("delta_db must be non-zero")

        self._pin = pin
        self._delta_db = delta_db
        self._delta_raw = int(round(delta_db / PLAYBACK_DB_PER_RAW_STEP))
        self._feedback_beeper = feedback_beeper
        self._mixer_card = _resolve_mixer_card(MIXER_CARD_NAME)
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_input(self._chip, self._pin, lgpio.SET_PULL_UP)

    def run(self) -> None:
        direction = "up" if self._delta_db > 0 else "down"
        print(
            f"[volume_button:{direction}] listening on GPIO {self._pin} "
            f"— press to change volume"
        )
        try:
            while True:
                if _button_pressed(self._chip, self._pin):
                    print(f"[GPIO {self._pin}] volume {direction}")
                    self._handle_press(direction)
        finally:
            lgpio.gpiochip_close(self._chip)

    def _handle_press(self, direction: str) -> None:
        try:
            level = self._adjust_volume()
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            print(f"[volume_button:{direction}] amixer failed: {detail}")
            return

        if level is None:
            print(f"[volume_button:{direction}] volume changed")
        else:
            print(
                f"[volume_button:{direction}] volume {direction} -> "
                f"{_format_volume(level)}"
            )
            self._play_feedback()

    def _adjust_volume(self) -> MixerLevel | None:
        current = subprocess.run(
            ["amixer", "-c", self._mixer_card, "get", MIXER_CONTROL],
            check=True,
            capture_output=True,
            text=True,
        )
        current_level = _parse_mixer_level(current.stdout)
        if current_level is None:
            return None

        target_raw = max(
            current_level.raw_min,
            min(current_level.raw_max, current_level.raw + self._delta_raw),
        )
        subprocess.run(
            ["amixer", "-c", self._mixer_card, "set", MIXER_CONTROL, str(target_raw)],
            check=True,
            capture_output=True,
            text=True,
        )

        updated = subprocess.run(
            ["amixer", "-c", self._mixer_card, "get", MIXER_CONTROL],
            check=True,
            capture_output=True,
            text=True,
        )
        return _parse_mixer_level(updated.stdout)

    def _play_feedback(self) -> None:
        if self._feedback_beeper is None:
            return
        self._feedback_beeper.beep_once(left=True, right=True)


def _parse_mixer_level(text: str) -> MixerLevel | None:
    limits = re.search(r"Limits:\s*(\d+)\s*-\s*(\d+)", text)
    channels = re.findall(
        r"Front (?:Left|Right):\s*(?:Playback\s+)?(\d+)\s+\[(\d+)%\](?:\s+\[([-\d.]+)dB\])?",
        text,
    )
    if limits is None or not channels:
        return None

    raw = int(channels[-1][0])
    percent = int(channels[-1][1])
    db_text = channels[-1][2]
    db = float(db_text) if db_text else None
    return MixerLevel(
        raw=raw,
        raw_min=int(limits.group(1)),
        raw_max=int(limits.group(2)),
        percent=percent,
        db=db,
    )


def _format_volume(level: MixerLevel) -> str:
    parts = []
    if level.percent is not None:
        parts.append(f"{level.percent}%")
    if level.db is not None:
        parts.append(f"{level.db:.1f} dB")
    parts.append(f"raw {level.raw}/{level.raw_max}")
    return " | ".join(parts)


def _resolve_mixer_card(card_name: str) -> str:
    cards_path = Path("/proc/asound/cards")
    try:
        text = cards_path.read_text()
    except OSError:
        return card_name

    for line in text.splitlines():
        match = re.match(r"\s*(\d+)\s+\[([^\]]+)\s*\]:", line)
        if match and match.group(2).strip() == card_name:
            return match.group(1)
    return card_name


def _button_pressed(chip: int, pin: int, debounce: float = 0.05) -> bool:
    """Return True once per press (active-low, waits for release)."""
    if lgpio.gpio_read(chip, pin) != 0:
        time.sleep(0.01)
        return False
    time.sleep(debounce)
    if lgpio.gpio_read(chip, pin) != 0:
        return False
    while lgpio.gpio_read(chip, pin) == 0:
        time.sleep(0.01)
    return True


if __name__ == "__main__":
    VolumeButton(pin=VOLUME_UP_PIN, delta_db=VOLUME_STEP_DB).run()
