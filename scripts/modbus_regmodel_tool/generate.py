#!/usr/bin/env python3
"""Тонкая точка входа: `python generate.py path/to/reg.yaml [--dry-run]`."""
from modbus_regmodel.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
