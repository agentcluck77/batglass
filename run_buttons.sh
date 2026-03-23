#!/usr/bin/env bash
cd "$(dirname "$0")"
sudo kill -9 $(sudo lsof -t /dev/gpiochip0 2>/dev/null) 2>/dev/null
sleep 0.3
PYTHONPATH=src:reference/hailo-apps hailort_version=5.2.0 .venv/bin/python -m buttons.__main__
