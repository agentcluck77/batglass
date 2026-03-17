"""Proximity sensor module for HC-SR04 ultrasonic distance measurement and beeping."""

from .beep import Beeper
from .sensor import ProximitySensor

__all__ = ["ProximitySensor", "Beeper"]
