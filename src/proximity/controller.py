#!/usr/bin/env python3
"""Dual-sensor echolocation runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time

from .beep import Beeper, _BEEP_DURATION_S
from .sensor import ProximitySensor

MAX_DISTANCE = 200.0  # cm
MIN_DISTANCE = 10.0   # cm
IDLE_SLEEP_S = 0.05
MAX_CONSECUTIVE_TIMEOUTS = 3


@dataclass(frozen=True)
class SensorConfig:
    name: str
    trig_pin: int
    echo_pin: int
    side: str


@dataclass
class SensorState:
    config: SensorConfig
    sensor: ProximitySensor
    distance_cm: float | None = None
    last_valid_distance_cm: float | None = None
    next_poll_at: float = 0.0
    next_beep_at: float = 0.0
    is_active: bool = False
    has_reported_timeout: bool = False
    consecutive_timeouts: int = 0
    last_printed_distance_cm: float | None = field(default=None, init=False)


# Default layout assumption:
# - existing sensor on GPIO 23/24 is mounted on the left side
# - second sensor uses GPIO 12/16 on the right side
# If your physical mounting is reversed, swap the `side` labels or CLI args.
DEFAULT_SENSOR_CONFIGS = (
    SensorConfig(name="left", trig_pin=23, echo_pin=24, side="left"),
    SensorConfig(name="right", trig_pin=12, echo_pin=16, side="right"),
)


class EcholocationController:
    def __init__(
        self,
        sensor_configs: tuple[SensorConfig, ...] = DEFAULT_SENSOR_CONFIGS,
        chip: int = 0,
        beeper: Beeper | None = None,
    ) -> None:
        self._beeper = beeper or Beeper()
        self._stop_event = threading.Event()
        self._closed = False
        self._states = [
            SensorState(
                config=config,
                sensor=ProximitySensor(
                    trig_pin=config.trig_pin,
                    echo_pin=config.echo_pin,
                    chip=chip,
                ),
            )
            for config in sensor_configs
        ]

        # Stagger the first poll slightly to reduce startup crosstalk.
        now = time.monotonic()
        for idx, state in enumerate(self._states):
            state.next_poll_at = now + (idx * 0.03)
            state.next_beep_at = now

    def run_forever(self) -> None:
        self._beeper.start()
        try:
            while not self._stop_event.is_set():
                now = time.monotonic()
                self._poll_sensors(now)
                now = time.monotonic()

                due_states = [
                    state
                    for state in self._states
                    if state.is_active and now >= state.next_beep_at
                ]
                if due_states:
                    self._play_due_beeps(due_states)
                    continue

                sleep_for = self._next_wake_delay(now)
                self._stop_event.wait(timeout=sleep_for)
        finally:
            self.close()

    def stop(self) -> None:
        self._stop_event.set()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for state in self._states:
            state.sensor.close()
        self._beeper.close()

    def _poll_sensors(self, now: float) -> None:
        for state in self._states:
            if now < state.next_poll_at:
                continue

            distance = state.sensor.get_distance()
            read_at = time.monotonic()
            state.next_poll_at = read_at + IDLE_SLEEP_S
            self._update_state(state, distance, read_at)

    def _update_state(self, state: SensorState, distance: float | None, now: float) -> None:
        if distance is None:
            state.consecutive_timeouts += 1
            state.distance_cm = state.last_valid_distance_cm
            if (
                state.consecutive_timeouts < MAX_CONSECUTIVE_TIMEOUTS
                and state.last_valid_distance_cm is not None
            ):
                return

            state.is_active = False
            if not state.has_reported_timeout:
                print(f"[echolocation:{state.config.name}] timeout")
                state.has_reported_timeout = True
            return

        state.distance_cm = distance
        state.last_valid_distance_cm = distance
        state.consecutive_timeouts = 0
        state.has_reported_timeout = False

        if (
            state.last_printed_distance_cm is None
            or abs(state.last_printed_distance_cm - distance) >= 5.0
        ):
            print(f"[echolocation:{state.config.name}] {distance:.2f} cm")
            state.last_printed_distance_cm = distance

        if distance > MAX_DISTANCE:
            state.is_active = False
            return

        if not state.is_active:
            state.next_beep_at = now
        state.is_active = True

    def _play_due_beeps(self, due_states: list[SensorState]) -> None:
        left = any(state.config.side == "left" for state in due_states)
        right = any(state.config.side == "right" for state in due_states)
        gaps_by_state = {id(state): _gap_for_distance(state.distance_cm) for state in due_states}
        self._beeper.beep(
            left=left,
            right=right,
            silence_after_s=min(gaps_by_state.values()),
        )

        played_at = time.monotonic()
        for state in due_states:
            gap_s = gaps_by_state[id(state)]
            state.next_beep_at = played_at + _BEEP_DURATION_S + gap_s

    def _next_wake_delay(self, now: float) -> float:
        next_times = [state.next_poll_at for state in self._states]
        next_times.extend(
            state.next_beep_at
            for state in self._states
            if state.is_active
        )
        if not next_times:
            return IDLE_SLEEP_S
        delay = min(next_times) - now
        return max(0.01, min(IDLE_SLEEP_S, delay))


def build_sensor_configs(
    *,
    left_trig: int = 23,
    left_echo: int = 24,
    right_trig: int = 12,
    right_echo: int = 16,
) -> tuple[SensorConfig, ...]:
    return (
        SensorConfig(name="left", trig_pin=left_trig, echo_pin=left_echo, side="left"),
        SensorConfig(name="right", trig_pin=right_trig, echo_pin=right_echo, side="right"),
    )


def probe_sensors(
    sensor_configs: tuple[SensorConfig, ...],
    *,
    samples: int = 5,
    chip: int = 0,
) -> None:
    sensors = [
        (
            config,
            ProximitySensor(trig_pin=config.trig_pin, echo_pin=config.echo_pin, chip=chip),
        )
        for config in sensor_configs
    ]
    try:
        for sample_idx in range(samples):
            print(f"[probe] sample {sample_idx + 1}/{samples}")
            for config, sensor in sensors:
                distance = sensor.get_distance()
                if distance is None:
                    print(
                        f"[probe:{config.name}] trig={config.trig_pin} "
                        f"echo={config.echo_pin} timeout"
                    )
                else:
                    print(
                        f"[probe:{config.name}] trig={config.trig_pin} "
                        f"echo={config.echo_pin} distance={distance:.2f} cm"
                    )
            time.sleep(0.1)
    finally:
        for _, sensor in sensors:
            sensor.close()


def _gap_for_distance(distance_cm: float | None) -> float:
    if distance_cm is None:
        return 0.5
    clamped = max(MIN_DISTANCE, min(distance_cm, MAX_DISTANCE))
    return 0.1 + ((clamped - MIN_DISTANCE) / (MAX_DISTANCE - MIN_DISTANCE)) * 1.4
