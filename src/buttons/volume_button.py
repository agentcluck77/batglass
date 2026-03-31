#!/usr/bin/env python3
"""GPIO 3 / 4 — adjust WM8960 speaker volume."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import lgpio

# -- config -------------------------------------------------------------------
VOLUME_UP_PIN = 3
VOLUME_DOWN_PIN = 4
MIXER_CARD_NAME = "wm8960soundcard"
# `Playback` is the stable master output control on this WM8960 setup.
MIXER_CONTROL = "Playback"
VOLUME_STEP_PERCENT = 5
# -----------------------------------------------------------------------------


class VolumeButton:
    def __init__(self, pin: int, delta_percent: int, chip: int = 0) -> None:
        if delta_percent == 0:
            raise ValueError("delta_percent must be non-zero")

        self._pin = pin
        self._delta_percent = delta_percent
        self._mixer_card = _resolve_mixer_card(MIXER_CARD_NAME)
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_input(self._chip, self._pin, lgpio.SET_PULL_UP)

    def run(self) -> None:
        direction = "up" if self._delta_percent > 0 else "down"
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
            volume = self._adjust_volume()
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            print(f"[volume_button:{direction}] amixer failed: {detail}")
            return

        if volume is None:
            print(f"[volume_button:{direction}] volume changed")
        else:
            print(f"[volume_button:{direction}] volume {direction} -> {volume}%")

    def _adjust_volume(self) -> int | None:
        current = subprocess.run(
            ["amixer", "-c", self._mixer_card, "get", MIXER_CONTROL],
            check=True,
            capture_output=True,
            text=True,
        )
        current_percent = _parse_volume_percent(current.stdout)
        if current_percent is None:
            return None

        target_percent = max(0, min(100, current_percent + self._delta_percent))
        subprocess.run(
            ["amixer", "-c", self._mixer_card, "set", MIXER_CONTROL, f"{target_percent}%"],
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
        return _parse_volume_percent(updated.stdout)


def _parse_volume_percent(text: str) -> int | None:
    matches = re.findall(r"\[(\d+)%\]", text)
    if not matches:
        return None
    return int(matches[-1])


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
    VolumeButton(pin=VOLUME_UP_PIN, delta_percent=VOLUME_STEP_PERCENT).run()
