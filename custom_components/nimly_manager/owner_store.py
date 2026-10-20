"""The lock's owner credential, kept in a private Home Assistant Store.

One record per config entry. The file (``.storage/nimly_manager.owner_keys``)
is written with mode 0600 by ``Store(private=True)``. Nothing in this module
logs the record, and only ``public_dict`` ever leaves it. Losing the key means
a module reset and a Zigbee re-pair, so the record is *not* deleted when the
config entry is removed; the user removes it deliberately.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .nimly_ble.keystore import KeyStoreError, OwnerRecord

STORAGE_KEY = f"{DOMAIN}.owner_keys"
STORAGE_VERSION = 1


class NimlyOwnerKeyStore:
    """Owner records keyed by config entry id."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, STORAGE_KEY, private=True, atomic_writes=True
        )
        self._records: dict[str, OwnerRecord] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if not isinstance(data, dict):
            return
        locks = data.get("locks")
        if not isinstance(locks, dict):
            return
        for entry_id, raw in locks.items():
            if not isinstance(raw, dict):
                continue
            try:
                self._records[str(entry_id)] = OwnerRecord(**raw)
            except TypeError:
                continue

    def get(self, entry_id: str) -> OwnerRecord | None:
        return self._records.get(entry_id)

    def has(self, entry_id: str) -> bool:
        return entry_id in self._records

    async def async_save_record(self, entry_id: str, record: OwnerRecord) -> None:
        """Persist before anything else may use the key."""

        if record.stage != "enrolled":
            raise KeyStoreError("bare en ferdig enrollet eierpost kan importeres")
        self._records[entry_id] = record
        await self._store.async_save(self._serialize())

    async def async_remove(self, entry_id: str) -> None:
        if self._records.pop(entry_id, None) is not None:
            await self._store.async_save(self._serialize())

    def _serialize(self) -> dict[str, Any]:
        return {
            "locks": {
                entry_id: record.as_dict() for entry_id, record in self._records.items()
            }
        }
