#!/usr/bin/env python3
"""Proximity beep loop: beep faster the closer an object is detected."""

from __future__ import annotations

import time

from .beep import Beeper
from .sensor import ProximitySensor

MAX_DISTANCE = 200  # cm — beyond this, stay silent
MIN_DISTANCE = 10   # cm — at this distance, beep interval is shortest


def main() -> None:
    sensor = ProximitySensor()
    beeper = Beeper()

    try:
        while True:
            distance = sensor.get_distance()

            if distance is None:
                time.sleep(0.5)
                continue

            print(f"Distance: {distance} cm")

            if distance > MAX_DISTANCE:
                time.sleep(0.5)
            else:
                clamped = max(MIN_DISTANCE, min(distance, MAX_DISTANCE))
                silence = 0.1 + ((clamped - MIN_DISTANCE) / (MAX_DISTANCE - MIN_DISTANCE)) * 1.4
                beeper.beep()
                time.sleep(silence)

    except KeyboardInterrupt:
        print("Stopped")
        sensor.close()


if __name__ == "__main__":
    main()
