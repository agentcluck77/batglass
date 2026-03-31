#!/usr/bin/env python3
"""GPIO 22 — Toggle echolocation (proximity beep loop) on/off."""

from __future__ import annotations

import threading
import time

import lgpio

from proximity.beep import Beeper, _BEEP_DURATION_S
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
                    print(f"[GPIO {BUTTON_PIN}] beep — echolocation toggle")
                    self._toggle()
        finally:
            self._active = False
            self._beeper.close()
            self._sensor.close()
            lgpio.gpiochip_close(self._chip)

    def _toggle(self) -> None:
        if self._active:
            self._active = False
            self._beeper.close()
            print("[beep_button] echolocation OFF")
        else:
            self._beeper.start()
            self._active = True
            print("[beep_button] echolocation ON")
            self._loop_thread = threading.Thread(target=self._echolocation_loop, daemon=True)
            self._loop_thread.start()

    def _echolocation_loop(self) -> None:
        while self._active:
            t0 = time.monotonic()
            distance = self._sensor.get_distance()
            elapsed = time.monotonic() - t0

            if distance is None:
                print("[echolocation] sensor timeout — no echo received")
                time.sleep(max(0.0, 0.5 - elapsed))
                continue

            print(f"[echolocation] {distance} cm")

            if distance > MAX_DISTANCE:
                time.sleep(max(0.0, 0.5 - elapsed))
            else:
                clamped = max(MIN_DISTANCE, min(distance, MAX_DISTANCE))
                gap = 0.1 + ((clamped - MIN_DISTANCE) / (MAX_DISTANCE - MIN_DISTANCE)) * 1.4
                # Write beep + silence as one chunk so the aplay stream is
                # never starved (preventing xrun/process-exit mid-session).
                self._beeper.beep(silence_after_s=gap)
                # Sleep for however much of the cycle remains after the sensor
                # read, so that write rate matches playback rate.
                cycle = _BEEP_DURATION_S + gap
                time.sleep(max(0.0, cycle - elapsed))


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
