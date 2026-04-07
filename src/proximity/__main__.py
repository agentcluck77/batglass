#!/usr/bin/env python3
"""Dual-sensor proximity runtime and probe CLI."""

from __future__ import annotations

import argparse

from .controller import EcholocationController, build_sensor_configs, probe_sensors


def main() -> None:
    args = _parse_args()
    sensor_configs = build_sensor_configs(
        left_trig=args.left_trig,
        left_echo=args.left_echo,
        right_trig=args.right_trig,
        right_echo=args.right_echo,
    )

    if args.probe:
        probe_sensors(sensor_configs, samples=args.samples)
        return

    controller = EcholocationController(sensor_configs=sensor_configs)
    try:
        controller.run_forever()
    except KeyboardInterrupt:
        print("Stopped")
        controller.stop()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dual-sensor echolocation runtime for BatGlass.",
    )
    parser.add_argument("--probe", action="store_true", help="Read sensors without playing audio.")
    parser.add_argument("--samples", type=int, default=5, help="Probe sample count.")
    parser.add_argument("--left-trig", type=int, default=23, help="Left sensor TRIG GPIO.")
    parser.add_argument("--left-echo", type=int, default=24, help="Left sensor ECHO GPIO.")
    parser.add_argument("--right-trig", type=int, default=12, help="Right sensor TRIG GPIO.")
    parser.add_argument("--right-echo", type=int, default=16, help="Right sensor ECHO GPIO.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
