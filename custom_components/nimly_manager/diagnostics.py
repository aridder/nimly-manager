"""Credential-safe diagnostics for Nimly Manager."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BASE_TOPIC,
    CONF_BLE_ADDRESS,
    CONF_DEVICE_NAME,
    DATA_OWNER_STORE,
    DATA_RUNTIMES,
    DOMAIN,
)
from .owner_store import NimlyOwnerKeyStore
from .runtime import NimlyLockRuntime


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return metadata without raw payloads, PINs or biometric material."""

    runtimes: dict[str, NimlyLockRuntime] = hass.data[DOMAIN][DATA_RUNTIMES]
    runtime = runtimes[entry.entry_id]
    store: NimlyOwnerKeyStore = hass.data[DOMAIN][DATA_OWNER_STORE]
    # The owner record itself never appears here: only whether one exists.
    return {
        "config": {
            CONF_BASE_TOPIC: entry.data[CONF_BASE_TOPIC],
            CONF_DEVICE_NAME: entry.data[CONF_DEVICE_NAME],
        },
        "ble": {
            "address_configured": bool(entry.options.get(CONF_BLE_ADDRESS)),
            "owner_key_imported": store.has(entry.entry_id),
        },
        "runtime": runtime.diagnostics(now=datetime.now(UTC)),
    }
