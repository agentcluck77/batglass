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
INTER_SENSOR_QUIET_S = 0.03
MAX_CONSECUTIVE_TIMEOUTS = 3
DISTANCE_SMOOTHING_ALPHA = 0.35
DIRECTION_ENABLE_DIFF_CM = 18.0
DIRECTION_HYSTERESIS_CM = 6.0
_CENTER_SIDE = "center"
_CENTER_BEEP_GAIN = 0.8
_BIASED_BEEP_GAIN = 0.45


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
    smoothed_distance_cm: float | None = None
    last_valid_distance_cm: float | None = None
    next_poll_at: float = 0.0
    is_active: bool = False
    has_reported_timeout: bool = False
    consecutive_timeouts: int = 0
    last_printed_distance_cm: float | None = field(default=None, init=False)


@dataclass(frozen=True)
class CueState:
    nearest_distance_cm: float
    dominant_side: str


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
        self._close_lock = threading.Lock()
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
        self._dominant_side = _CENTER_SIDE
        self._next_beep_at = 0.0

        # Stagger the first poll slightly to reduce startup crosstalk.
        now = time.monotonic()
        for idx, state in enumerate(self._states):
            state.next_poll_at = now + (idx * 0.03)
        self._next_beep_at = now

    def run_forever(self) -> None:
        self._beeper.start()
        try:
            while not self._stop_event.is_set():
                now = time.monotonic()
                self._poll_sensors(now)
                now = time.monotonic()

                cue_state = self._build_cue_state()
                if cue_state is not None and now >= self._next_beep_at:
                    self._play_cue(cue_state)
                    continue

                sleep_for = self._next_wake_delay(now, cue_state)
                self._stop_event.wait(timeout=sleep_for)
        finally:
            self.close()

    def stop(self) -> None:
        self._stop_event.set()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True

        self._stop_event.set()
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
            self._push_other_sensor_polls(state, read_at)
            self._update_state(state, distance, read_at)

    def _push_other_sensor_polls(self, just_read: SensorState, read_at: float) -> None:
        quiet_until = read_at + INTER_SENSOR_QUIET_S
        for state in self._states:
            if state is just_read:
                continue
            if state.next_poll_at < quiet_until:
                state.next_poll_at = quiet_until

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
        state.smoothed_distance_cm = _smooth_distance(
            previous=state.smoothed_distance_cm,
            current=distance,
        )
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

        state.is_active = True

    def _build_cue_state(self) -> CueState | None:
        distances_by_side = {
            state.config.side: state.smoothed_distance_cm
            for state in self._states
            if state.is_active and state.smoothed_distance_cm is not None
        }
        if not distances_by_side:
            self._dominant_side = _CENTER_SIDE
            return None

        nearest_distance_cm = min(distances_by_side.values())
        dominant_side = self._resolve_dominant_side(distances_by_side)
        self._dominant_side = dominant_side
        return CueState(
            nearest_distance_cm=nearest_distance_cm,
            dominant_side=dominant_side,
        )

    def _resolve_dominant_side(self, distances_by_side: dict[str, float]) -> str:
        left_distance = distances_by_side.get("left")
        right_distance = distances_by_side.get("right")

        if left_distance is None and right_distance is None:
            return _CENTER_SIDE
        if left_distance is None:
            return "right"
        if right_distance is None:
            return "left"

        difference_cm = abs(left_distance - right_distance)
        closer_side = "left" if left_distance < right_distance else "right"
        keep_threshold = max(0.0, DIRECTION_ENABLE_DIFF_CM - DIRECTION_HYSTERESIS_CM)
        switch_threshold = DIRECTION_ENABLE_DIFF_CM + DIRECTION_HYSTERESIS_CM

        if self._dominant_side == _CENTER_SIDE:
            return closer_side if difference_cm >= DIRECTION_ENABLE_DIFF_CM else _CENTER_SIDE
        if self._dominant_side == closer_side:
            return closer_side if difference_cm >= keep_threshold else _CENTER_SIDE
        if difference_cm >= switch_threshold:
            return closer_side
        if difference_cm >= keep_threshold:
            return self._dominant_side
        return _CENTER_SIDE

    def _play_cue(self, cue_state: CueState) -> None:
        left_gain, right_gain = _gains_for_side(cue_state.dominant_side)
        gap_s = _gap_for_distance(cue_state.nearest_distance_cm)
        self._beeper.beep(
            left_gain=left_gain,
            right_gain=right_gain,
        )
        played_at = time.monotonic()
        self._next_beep_at = played_at + _BEEP_DURATION_S + gap_s

    def _next_wake_delay(self, now: float, cue_state: CueState | None) -> float:
        next_times = [state.next_poll_at for state in self._states]
        if cue_state is not None:
            next_times.append(self._next_beep_at)
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
    if clamped <= 15.0:
        return 0.02
    if clamped <= 30.0:
        return 0.08
    if clamped <= 60.0:
        return 0.18
    if clamped <= 100.0:
        return 0.35
    if clamped <= 150.0:
        return 0.6
    return 0.9


def _smooth_distance(*, previous: float | None, current: float) -> float:
    if previous is None:
        return current
    return (DISTANCE_SMOOTHING_ALPHA * current) + ((1.0 - DISTANCE_SMOOTHING_ALPHA) * previous)


def _gains_for_side(side: str) -> tuple[float, float]:
    if side == "left":
        return (1.0, _BIASED_BEEP_GAIN)
    if side == "right":
        return (_BIASED_BEEP_GAIN, 1.0)
    return (_CENTER_BEEP_GAIN, _CENTER_BEEP_GAIN)
