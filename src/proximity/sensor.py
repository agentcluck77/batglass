#!/usr/bin/env python3
"""HC-SR04 ultrasonic proximity sensor driver."""

from __future__ import annotations

import threading
import time

import lgpio


_SPEED_OF_SOUND_CM_PER_S = 34300
_DEFAULT_MAX_DISTANCE_CM = 400.0
_MIN_VALID_DISTANCE_CM = 2.0


class ProximitySensor:
    def __init__(
        self,
        trig_pin: int = 23,
        echo_pin: int = 24,
        chip: int = 0,
        max_distance_cm: float = _DEFAULT_MAX_DISTANCE_CM,
    ):
        self._trig = trig_pin
        self._echo = echo_pin
        self._max_distance_cm = max_distance_cm
        self._timeout_s = ((max_distance_cm * 2) / _SPEED_OF_SOUND_CM_PER_S) + 0.01
        self._chip = lgpio.gpiochip_open(chip)
        lgpio.gpio_claim_output(self._chip, self._trig, 0)
        lgpio.gpio_claim_alert(self._chip, self._echo, lgpio.BOTH_EDGES)

        self._rise_tick: int | None = None
        self._last_distance: float | None = None
        self._event = threading.Event()
        self._measure_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._measuring = False
        self._closed = False

        self._cb = lgpio.callback(self._chip, self._echo, lgpio.BOTH_EDGES, self._edge)

    def _edge(self, chip: int, gpio: int, level: int, tick: int) -> None:
        with self._state_lock:
            if self._closed or not self._measuring:
                return

            if level == 1:
                self._rise_tick = tick
                self._event.clear()
            elif level == 0 and self._rise_tick is not None:
                pulse_ns = tick - self._rise_tick
                distance_cm = round((pulse_ns / 1e9) * (_SPEED_OF_SOUND_CM_PER_S / 2), 2)
                self._rise_tick = None
                if _MIN_VALID_DISTANCE_CM <= distance_cm <= self._max_distance_cm:
                    self._last_distance = distance_cm
                    self._event.set()

    def get_distance(self) -> float | None:
        """Return distance in cm, or None on timeout."""
        with self._measure_lock:
            with self._state_lock:
                if self._closed:
                    return None
                self._event.clear()
                self._rise_tick = None
                self._last_distance = None
                self._measuring = True

            try:
                lgpio.gpio_write(self._chip, self._trig, 0)
                time.sleep(0.000002)
                lgpio.gpio_write(self._chip, self._trig, 1)
                time.sleep(0.00001)
                lgpio.gpio_write(self._chip, self._trig, 0)
            except lgpio.error:
                with self._state_lock:
                    self._measuring = False
                    self._event.clear()
                    if self._closed:
                        return None
                raise

            got_distance = self._event.wait(timeout=self._timeout_s)
            with self._state_lock:
                distance = self._last_distance if got_distance else None
                self._rise_tick = None
                self._last_distance = None
                self._measuring = False
                self._event.clear()
                return distance

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            with self._state_lock:
                self._measuring = False
                self._rise_tick = None
                self._last_distance = None
                self._event.set()
            self._cb.cancel()
            lgpio.gpiochip_close(self._chip)
