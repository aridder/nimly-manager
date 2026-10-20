"""BLE address and owner-key setup, shared by the options flow and the panel.

The panel is registered as the integration's config panel, so Home
Assistant's gear icon opens the panel, not the options flow. The panel
therefore needs the same setup step; both go through here.
"""

from __future__ import annotations

import re

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BLE_ADDRESS,
    DATA_OWNER_STORE,
    DOMAIN,
    OPTION_OWNER_KEY_IMPORTED,
    OPTION_OWNER_NAME,
)
from .nimly_ble.constants import NIMLY_ADVERTISING_UUID
from .nimly_ble.keystore import KeyStoreError, OwnerRecord, owner_record_from_json
from .owner_store import NimlyOwnerKeyStore

MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


class BleSetupError(ValueError):
    """User-facing setup error; never contains key material."""


def normalize_mac(value: str) -> str | None:
    cleaned = value.strip().upper().replace("-", ":")
    if len(cleaned) == 12 and ":" not in cleaned:
        cleaned = ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))
    return cleaned if MAC_RE.match(cleaned) else None


def discovered_nimly_locks(hass: HomeAssistant) -> list[dict[str, object]]:
    """Connectable advertisements carrying Nimly's 0xFD00 service data."""

    found: list[dict[str, object]] = []
    for info in bluetooth.async_discovered_service_info(hass, connectable=True):
        if NIMLY_ADVERTISING_UUID not in info.service_data:
            continue
        seed = bytes(info.service_data[NIMLY_ADVERTISING_UUID])[:2]
        found.append(
            {
                "address": info.address,
                "name": info.name or "Nimly",
                "rssi": info.rssi,
                "source": info.source,
                "enrollment_state": (
                    "enrolled" if seed and seed != b"\x00\x00" else "factory"
                ),
            }
        )
    return found


def parse_owner_record(pasted: str | None) -> OwnerRecord | None:
    text = (pasted or "").strip()
    if not text:
        return None
    try:
        return owner_record_from_json(text)
    except KeyStoreError as error:
        raise BleSetupError(f"eierposten er ugyldig: {error}") from error


async def async_apply_ble_setup(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    address: str,
    record: OwnerRecord | None,
    remove_owner_key: bool = False,
) -> dict[str, object]:
    """Store the key (if any) before touching options; options reload the entry."""

    normalized = normalize_mac(address)
    if normalized is None:
        raise BleSetupError("BLE-adressen må være på formen AA:BB:CC:DD:EE:FF")
    store: NimlyOwnerKeyStore = hass.data[DOMAIN][DATA_OWNER_STORE]
    options = dict(entry.options)
    if remove_owner_key:
        await store.async_remove(entry.entry_id)
        options.pop(OPTION_OWNER_NAME, None)
    elif record is not None:
        await store.async_save_record(entry.entry_id, record)
        options[OPTION_OWNER_NAME] = record.name or None
    options[CONF_BLE_ADDRESS] = normalized
    options[OPTION_OWNER_KEY_IMPORTED] = store.has(entry.entry_id)
    return options
