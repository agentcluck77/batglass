#!/usr/bin/env python3
"""HC-SR04 ultrasonic proximity sensor driver."""

from __future__ import annotations

import time

import lgpio


class ProximitySensor:
    def __init__(self, trig_pin: int = 23, echo_pin: int = 24, chip: int = 0):
        self._trig = trig_pin
        self._echo = echo_pin
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_output(self._chip, self._trig)
        lgpio.gpio_claim_input(self._chip, self._echo)

    def get_distance(self) -> float | None:
        """Return distance in cm, or None on timeout."""
        lgpio.gpio_write(self._chip, self._trig, 0)
        time.sleep(0.05)

        lgpio.gpio_write(self._chip, self._trig, 1)
        time.sleep(0.00001)
        lgpio.gpio_write(self._chip, self._trig, 0)

        timeout = time.time() + 1
        while lgpio.gpio_read(self._chip, self._echo) == 0:
            pulse_start = time.time()
            if time.time() > timeout:
                return None

        timeout = time.time() + 1
        while lgpio.gpio_read(self._chip, self._echo) == 1:
            pulse_end = time.time()
            if time.time() > timeout:
                return None

        pulse_duration = pulse_end - pulse_start
        return round(pulse_duration * 17150, 2)

    def close(self) -> None:
        lgpio.gpiochip_close(self._chip)
