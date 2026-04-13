#!/usr/bin/env python3
"""GPIO 22 — Toggle echolocation (proximity beep loop) on/off."""

from __future__ import annotations

import threading
import time

import lgpio

from proximity.beep import Beeper
from proximity.controller import EcholocationController

# -- config -------------------------------------------------------------------
BUTTON_PIN   = 22
# -----------------------------------------------------------------------------


class BeepButton:
    def __init__(self, chip: int = 0, beeper: Beeper | None = None) -> None:
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_input(self._chip, BUTTON_PIN, lgpio.SET_PULL_UP)
        self._active = False
        self._beeper = beeper
        self._controller: EcholocationController | None = None
        self._loop_thread: threading.Thread | None = None
        self._state_lock = threading.Lock()

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
        with self._state_lock:
            is_active = self._active

        if is_active:
            self._stop_controller()
            print("[beep_button] echolocation OFF")
            return

        controller = EcholocationController(beeper=self._beeper)
        loop_thread = threading.Thread(
            target=self._run_controller,
            args=(controller,),
            daemon=True,
        )
        with self._state_lock:
            self._active = True
            self._controller = controller
            self._loop_thread = loop_thread

        print("[beep_button] echolocation ON")
        loop_thread.start()

    def _run_controller(self, controller: EcholocationController) -> None:
        try:
            controller.run_forever()
        finally:
            with self._state_lock:
                if self._controller is controller:
                    self._controller = None
                    self._loop_thread = None
                    self._active = False

    def _stop_controller(self) -> None:
        with self._state_lock:
            controller = self._controller
            loop_thread = self._loop_thread
            self._active = False
            self._controller = None
            self._loop_thread = None

        if controller is not None:
            controller.stop()
        if loop_thread is not None:
            loop_thread.join(timeout=1.0)
            if loop_thread.is_alive():
                print("[beep_button] controller thread did not stop within 1.0s")
        if controller is not None:
            controller.close()


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
