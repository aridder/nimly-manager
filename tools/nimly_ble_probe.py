#!/usr/bin/env python3
"""Development entry point; prefer the installed ``nimly-ble-probe`` command."""

from nimly_ble_probe.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
