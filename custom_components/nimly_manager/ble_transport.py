"""``nimly_ble`` transport over Home Assistant's bluetooth integration.

Same interface as ``nimly_ble.transport_bleak.BleakTransport`` (``write`` and
``set_notify_handler``), but the connection comes from HA's stack, so an
ESPHome ``bluetooth_proxy`` near the door is used transparently.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Self

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .nimly_ble.constants import NIMLY_COMMUNICATION_UUID, SOFTWARE_REVISION_UUID

_LOGGER = logging.getLogger(__name__)

CONNECT_ATTEMPTS = 3


class LockNotVisibleError(RuntimeError):
    """HA (including its proxies) has no connectable advertisement for the lock."""


class HomeAssistantTransport:
    """Writes with response; the lock's reassembly expects orderly frames."""

    def __init__(self, hass: HomeAssistant, address: str, *, name: str) -> None:
        self._hass = hass
        self._address = address
        self._name = name
        self._client: BleakClientWithServiceCache | None = None
        self._handler: Callable[[bytes], None] | None = None
        self.disconnected = False

    def _device(self) -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(
            self._hass, self._address, connectable=True
        )

    async def __aenter__(self) -> Self:
        device = self._device()
        if device is None:
            raise LockNotVisibleError(
                "Home Assistant ser ingen tilkoblbar annonsering fra låsen. "
                "Sjekk Bluetooth-proxyen ved døra."
            )
        self._client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            self._name,
            disconnected_callback=self._on_disconnect,
            max_attempts=CONNECT_ATTEMPTS,
            ble_device_callback=self._device,
        )
        await self._client.start_notify(NIMLY_COMMUNICATION_UUID, self._on_notify)
        return self

    async def __aexit__(self, *exc: object) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            if client.is_connected:
                await client.stop_notify(NIMLY_COMMUNICATION_UUID)
        except Exception:
            _LOGGER.debug("stop_notify feilet ved frakobling", exc_info=True)
        finally:
            await client.disconnect()

    def _on_disconnect(self, _client: Any) -> None:
        self.disconnected = True
        _LOGGER.debug("låsen koblet fra")

    def _on_notify(self, _characteristic: Any, data: bytearray) -> None:
        if self._handler is not None:
            self._handler(bytes(data))

    def set_notify_handler(self, handler: Callable[[bytes], None]) -> None:
        self._handler = handler

    async def write(self, data: bytes) -> None:
        if self._client is None:
            raise RuntimeError("transporten er ikke tilkoblet")
        await self._client.write_gatt_char(
            NIMLY_COMMUNICATION_UUID, data, response=True
        )

    async def read_software_revision(self) -> str:
        if self._client is None:
            raise RuntimeError("transporten er ikke tilkoblet")
        value = await self._client.read_gatt_char(SOFTWARE_REVISION_UUID)
        return bytes(value).rstrip(b"\x00").decode("utf-8", errors="replace")


def ble_status(hass: HomeAssistant, address: str | None) -> dict[str, object]:
    """What the panel may show about reachability: no identifiers beyond the MAC."""

    if not address:
        return {"address": None, "visible": False, "rssi": None, "source": None}
    info = bluetooth.async_last_service_info(hass, address, connectable=True)
    return {
        "address": address,
        "visible": info is not None,
        "rssi": info.rssi if info is not None else None,
        "source": info.source if info is not None else None,
    }
