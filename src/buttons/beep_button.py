#!/usr/bin/env python3
"""GPIO 22 — Toggle echolocation (proximity beep loop) on/off."""

from __future__ import annotations

import threading
import time

import lgpio

from proximity.beep import Beeper
from proximity.sensor import ProximitySensor

# -- config -------------------------------------------------------------------
BUTTON_PIN   = 22
MAX_DISTANCE = 200  # cm
MIN_DISTANCE = 10   # cm
# -----------------------------------------------------------------------------


class BeepButton:
    def __init__(self, chip: int = 0) -> None:
        self._sensor = ProximitySensor()
        self._beeper = Beeper()
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_input(self._chip, BUTTON_PIN, lgpio.SET_PULL_UP)
        self._active = False
        self._loop_thread: threading.Thread | None = None

    def run(self) -> None:
        print(f"[beep_button] listening on GPIO {BUTTON_PIN} — press to toggle echolocation")
        try:
            while True:
                if _button_pressed(self._chip, BUTTON_PIN):
                    self._toggle()
        finally:
            self._active = False
            self._sensor.close()
            lgpio.gpiochip_close(self._chip)

    def _toggle(self) -> None:
        if self._active:
            self._active = False
            print("[beep_button] echolocation OFF")
        else:
            self._active = True
            print("[beep_button] echolocation ON")
            self._loop_thread = threading.Thread(target=self._echolocation_loop, daemon=True)
            self._loop_thread.start()

    def _echolocation_loop(self) -> None:
        while self._active:
            distance = self._sensor.get_distance()

            if distance is None:
                time.sleep(0.5)
                continue

            print(f"[echolocation] {distance} cm")

            if distance > MAX_DISTANCE:
                time.sleep(0.5)
            else:
                clamped = max(MIN_DISTANCE, min(distance, MAX_DISTANCE))
                silence = 0.1 + ((clamped - MIN_DISTANCE) / (MAX_DISTANCE - MIN_DISTANCE)) * 1.4
                self._beeper.beep()
                time.sleep(silence)


def _button_pressed(chip: int, pin: int, debounce: float = 0.05) -> bool:
    """Return True once per press (active-low, waits for release)."""
    if lgpio.gpio_read(chip, pin) != 0:
        time.sleep(0.01)  # idle sleep to avoid busy-loop
        return False
    time.sleep(debounce)
    if lgpio.gpio_read(chip, pin) != 0:
        return False
    while lgpio.gpio_read(chip, pin) == 0:
        time.sleep(0.01)
    return True


if __name__ == "__main__":
    BeepButton().run()
