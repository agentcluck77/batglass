#!/usr/bin/env python3
"""GPIO 22 — Toggle echolocation (proximity beep loop) on/off."""

from __future__ import annotations

import threading
import time

import lgpio

from proximity.controller import EcholocationController

# -- config -------------------------------------------------------------------
BUTTON_PIN   = 22
# -----------------------------------------------------------------------------


class BeepButton:
    def __init__(self, chip: int = 0) -> None:
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_input(self._chip, BUTTON_PIN, lgpio.SET_PULL_UP)
        self._active = False
        self._controller: EcholocationController | None = None
        self._loop_thread: threading.Thread | None = None

    def run(self) -> None:
        print(f"[beep_button] listening on GPIO {BUTTON_PIN} — press to toggle echolocation")
        try:
            while True:
                if _button_pressed(self._chip, BUTTON_PIN):
                    print(f"[GPIO {BUTTON_PIN}] beep — echolocation toggle")
                    self._toggle()
        finally:
            self._stop_controller()
            lgpio.gpiochip_close(self._chip)

    def _toggle(self) -> None:
        if self._active:
            self._active = False
            self._stop_controller()
            print("[beep_button] echolocation OFF")
        else:
            self._active = True
            self._controller = EcholocationController()
            print("[beep_button] echolocation ON")
            self._loop_thread = threading.Thread(target=self._run_controller, daemon=True)
            self._loop_thread.start()

    def _run_controller(self) -> None:
        controller = self._controller
        if controller is None:
            return
        try:
            controller.run_forever()
        finally:
            self._controller = None
            self._active = False

    def _stop_controller(self) -> None:
        controller = self._controller
        if controller is not None:
            controller.stop()
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=1.0)
            self._loop_thread = None
        if controller is not None:
            controller.close()
            self._controller = None


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
