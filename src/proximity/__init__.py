"""Proximity sensor module for HC-SR04 ultrasonic distance measurement and beeping."""

from .beep import Beeper
from .controller import (
    DEFAULT_SENSOR_CONFIGS,
    EcholocationController,
    SensorConfig,
    build_sensor_configs,
    probe_sensors,
)
from .sensor import ProximitySensor

__all__ = [
    "Beeper",
    "DEFAULT_SENSOR_CONFIGS",
    "EcholocationController",
    "ProximitySensor",
    "SensorConfig",
    "build_sensor_configs",
    "probe_sensors",
]
