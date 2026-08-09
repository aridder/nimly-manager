"""Conservative capability gates derived from the documented BLE protocol."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class FirmwareVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> FirmwareVersion | None:
        parts = value.strip().split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return None
        return cls(*(int(part) for part in parts))


def compatibility_for(value: str) -> dict[str, bool | str]:
    """Report only capabilities with a documented firmware boundary."""

    version = FirmwareVersion.parse(value)
    if version is None:
        return {
            "firmware_parsed": False,
            "ble_connection_documented": "unknown",
            "device_model_query_documented": "unknown",
            "fingerprint_enrollment": "unverified",
        }

    return {
        "firmware_parsed": True,
        "ble_connection_documented": version >= FirmwareVersion(4, 6, 0),
        "device_model_query_documented": version >= FirmwareVersion(4, 7, 90),
        "fingerprint_enrollment": "unverified",
    }
