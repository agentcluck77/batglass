#!/usr/bin/env python3
"""HC-SR04 ultrasonic proximity sensor driver."""

from __future__ import annotations

import threading
import time

import lgpio


class ProximitySensor:
    def __init__(self, trig_pin: int = 23, echo_pin: int = 24, chip: int = 0):
        self._trig = trig_pin
        self._echo = echo_pin
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_output(self._chip, self._trig, 0)
        lgpio.gpio_claim_alert(self._chip, self._echo, lgpio.BOTH_EDGES)

        self._rise_tick: int | None = None
        self._event = threading.Event()

        self._cb = lgpio.callback(self._chip, self._echo, lgpio.BOTH_EDGES, self._edge)

    def _edge(self, chip: int, gpio: int, level: int, tick: int) -> None:
        if level == 1:
            self._rise_tick = tick
            self._event.clear()
        elif level == 0 and self._rise_tick is not None:
            pulse_ns = tick - self._rise_tick
            self._last_distance = round((pulse_ns / 1e9) * 17150, 2)
            self._rise_tick = None
            self._event.set()

    def get_distance(self) -> float | None:
        """Return distance in cm, or None on timeout."""
        self._event.clear()
        self._rise_tick = None

        lgpio.gpio_write(self._chip, self._trig, 0)
        time.sleep(0.05)
        lgpio.gpio_write(self._chip, self._trig, 1)
        time.sleep(0.00001)
        lgpio.gpio_write(self._chip, self._trig, 0)

        if self._event.wait(timeout=1.0):
            return self._last_distance
        return None

    def close(self) -> None:
        self._cb.cancel()
        lgpio.gpiochip_close(self._chip)
