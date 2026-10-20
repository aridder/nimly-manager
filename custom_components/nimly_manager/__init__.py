"""Nimly Manager custom integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_BASE_TOPIC,
    CONF_DEVICE_NAME,
    DATA_OWNER_STORE,
    DATA_RUNTIMES,
    DATA_SCAN_COORDINATOR,
    DATA_SLOT_STORAGE,
    DATA_WEBSOCKET_REGISTERED,
    DOMAIN,
    state_topic,
)
from .owner_store import NimlyOwnerKeyStore
from .runtime import NimlyLockRuntime
from .storage import NimlySlotStorage

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration and register its actions."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data.setdefault(DATA_RUNTIMES, {})
    from .services import async_setup_services
    from .websocket import async_register_websocket_api

    async_setup_services(hass)
    if DATA_SLOT_STORAGE not in domain_data:
        storage = NimlySlotStorage(hass)
        await storage.async_load()
        domain_data[DATA_SLOT_STORAGE] = storage
    if DATA_OWNER_STORE not in domain_data:
        owner_store = NimlyOwnerKeyStore(hass)
        await owner_store.async_load()
        domain_data[DATA_OWNER_STORE] = owner_store
    if DATA_SCAN_COORDINATOR not in domain_data:
        from .ble_scan import FingerprintScanCoordinator

        domain_data[DATA_SCAN_COORDINATOR] = FingerprintScanCoordinator(hass)
    if not domain_data.get(DATA_WEBSOCKET_REGISTERED):
        async_register_websocket_api(hass)
        domain_data[DATA_WEBSOCKET_REGISTERED] = True
    from .panel import async_register_panel

    await async_register_panel(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MQTT observation for one Nimly lock."""

    from .mqtt import async_subscribe_state

    domain_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {DATA_RUNTIMES: {}})
    runtimes: dict[str, NimlyLockRuntime] = domain_data.setdefault(DATA_RUNTIMES, {})
    storage: NimlySlotStorage = domain_data[DATA_SLOT_STORAGE]
    runtime = NimlyLockRuntime(
        topic=state_topic(
            entry.data[CONF_BASE_TOPIC],
            entry.data[CONF_DEVICE_NAME],
        ),
        slots=storage.registry_for(entry.entry_id),
    )
    runtimes[entry.entry_id] = runtime
    try:
        await async_subscribe_state(hass, entry, runtime)
    except Exception:
        runtimes.pop(entry.entry_id, None)
        raise
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options (BLE address, imported key) changed: reload the lock."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one lock runtime; entry callbacks remove MQTT subscriptions."""

    domain_data = hass.data[DOMAIN]
    if (coordinator := domain_data.get(DATA_SCAN_COORDINATOR)) is not None:
        coordinator.async_cancel(entry.entry_id)
    domain_data[DATA_RUNTIMES].pop(entry.entry_id, None)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete slot metadata when the lock entry itself is deleted.

    The owner key is kept on purpose: losing it means a module reset and a
    Zigbee re-pair. Remove it deliberately via the options flow.
    """

    storage: NimlySlotStorage = hass.data[DOMAIN][DATA_SLOT_STORAGE]
    await storage.async_remove_entry(entry.entry_id)
