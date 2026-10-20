"""GATT identifiers the owner tooling needs, kept local so the package has no
dependency on ``nimly_ble_probe`` when it ships inside the integration."""

NIMLY_SERVICE_UUID = "ba4bfd00-c447-19bf-f38d-4890b3a824c8"
NIMLY_COMMUNICATION_UUID = "ba4bfd03-c447-19bf-f38d-4890b3a824c8"
NIMLY_ADVERTISING_UUID = "0000fd00-0000-1000-8000-00805f9b34fb"
SOFTWARE_REVISION_UUID = "00002a28-0000-1000-8000-00805f9b34fb"


def parse_firmware(value: str) -> tuple[int, int, int] | None:
    """Parse ``major.minor.patch`` from the Software Revision string."""

    parts = value.strip().strip("\x00").split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    major, minor, patch = (int(part) for part in parts)
    return major, minor, patch
