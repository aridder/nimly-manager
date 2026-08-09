"""Nimly Manager custom integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_BASE_TOPIC,
    CONF_DEVICE_NAME,
    DATA_RUNTIMES,
    DOMAIN,
    state_topic,
)
from .runtime import NimlyLockRuntime

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration and register its actions."""

    hass.data.setdefault(DOMAIN, {DATA_RUNTIMES: {}})
    from .services import async_setup_services

    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MQTT observation for one Nimly lock."""

    from .mqtt import async_subscribe_state

    domain_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {DATA_RUNTIMES: {}})
    runtimes: dict[str, NimlyLockRuntime] = domain_data.setdefault(DATA_RUNTIMES, {})
    runtime = NimlyLockRuntime(
        topic=state_topic(
            entry.data[CONF_BASE_TOPIC],
            entry.data[CONF_DEVICE_NAME],
        )
    )
    runtimes[entry.entry_id] = runtime
    try:
        await async_subscribe_state(hass, entry, runtime)
    except Exception:
        runtimes.pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one lock runtime; entry callbacks remove MQTT subscriptions."""

    hass.data[DOMAIN][DATA_RUNTIMES].pop(entry.entry_id, None)
    return True
