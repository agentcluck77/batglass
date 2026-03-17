#!/usr/bin/env python3
"""Thin shim — delegates to camera_ocr.snap_cli (installed via uv)."""
from camera_ocr.snap_cli import main

raise SystemExit(main())
