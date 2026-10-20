"""Nimly BLE owner tooling: link crypto, framing and the owner-enrollment flow.

Separate from ``nimly_ble_probe`` on purpose: the probe stays read-only, this
package writes to the lock. Protocol mechanics follow onesti-lock's
``docs/nimly-ble-app/`` notes; nothing here has been run against hardware
before 2026-10-20.
"""
