"""bleak transport for a laptop next to the door."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nimly_ble_probe.constants import (
    NIMLY_COMMUNICATION_UUID,
    SOFTWARE_REVISION_UUID,
)


class BleakTransport:
    """Writes with response; the lock's reassembly expects orderly frames."""

    def __init__(self, device: Any, *, timeout: float = 20.0) -> None:
        from bleak import BleakClient

        self._client = BleakClient(device, timeout=timeout)
        self._handler: Callable[[bytes], None] | None = None

    async def __aenter__(self) -> BleakTransport:
        await self._client.connect()
        await self._client.start_notify(NIMLY_COMMUNICATION_UUID, self._on_notify)
        return self

    async def __aexit__(self, *exc: object) -> None:
        try:
            await self._client.stop_notify(NIMLY_COMMUNICATION_UUID)
        finally:
            await self._client.disconnect()

    def _on_notify(self, _characteristic: Any, data: bytearray) -> None:
        if self._handler is not None:
            self._handler(bytes(data))

    def set_notify_handler(self, handler: Callable[[bytes], None]) -> None:
        self._handler = handler

    async def write(self, data: bytes) -> None:
        await self._client.write_gatt_char(NIMLY_COMMUNICATION_UUID, data, response=True)

    async def read_software_revision(self) -> str:
        value = await self._client.read_gatt_char(SOFTWARE_REVISION_UUID)
        return bytes(value).rstrip(b"\x00").decode("utf-8", errors="replace")
