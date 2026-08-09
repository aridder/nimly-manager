"""Credential-safe diagnostics for Nimly Manager."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BASE_TOPIC,
    CONF_DEVICE_NAME,
    DATA_RUNTIMES,
    DOMAIN,
)
from .runtime import NimlyLockRuntime


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return metadata without raw payloads, PINs or biometric material."""

    runtimes: dict[str, NimlyLockRuntime] = hass.data[DOMAIN][DATA_RUNTIMES]
    runtime = runtimes[entry.entry_id]
    return {
        "config": {
            CONF_BASE_TOPIC: entry.data[CONF_BASE_TOPIC],
            CONF_DEVICE_NAME: entry.data[CONF_DEVICE_NAME],
        },
        "runtime": runtime.diagnostics(now=datetime.now(UTC)),
    }
