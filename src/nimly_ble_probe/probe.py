"""Bleak adapter for read-only Nimly discovery and GATT inspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .advertisement import NimlyAdvertisement, inspect_advertisement
from .constants import SOFTWARE_REVISION_UUID


class BleUnavailableError(RuntimeError):
    """Raised when the optional BLE runtime is unavailable."""


@dataclass(frozen=True, slots=True)
class DiscoveredNimly:
    advertisement: NimlyAdvertisement
    device: Any


def _load_bleak() -> tuple[Any, Any]:
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError as error:
        raise BleUnavailableError(
            "BLE-støtte mangler. Kjør med `uv run --extra ble nimly-ble-probe ...`."
        ) from error
    return BleakClient, BleakScanner


async def discover_nimly(timeout: float) -> list[DiscoveredNimly]:
    """Scan passively and return only advertisements matching Nimly UUIDs."""

    _, scanner = _load_bleak()
    discovered = await scanner.discover(timeout=timeout, return_adv=True)
    result: list[DiscoveredNimly] = []

    for device, advertisement in discovered.values():
        candidate = inspect_advertisement(
            address=str(device.address),
            name=device.name or advertisement.local_name,
            service_uuids=advertisement.service_uuids,
            service_data=advertisement.service_data,
            rssi=getattr(advertisement, "rssi", None),
        )
        if candidate is not None:
            result.append(DiscoveredNimly(candidate, device))

    result.sort(key=lambda item: item.advertisement.probe_id)
    return result


async def read_software_revision(device: Any, timeout: float) -> str:
    """Read the standard Device Information characteristic; never write."""

    client_class, _ = _load_bleak()
    async with client_class(device, timeout=timeout) as client:
        value = await client.read_gatt_char(SOFTWARE_REVISION_UUID)
    return bytes(value).rstrip(b"\x00").decode("utf-8", errors="replace")
