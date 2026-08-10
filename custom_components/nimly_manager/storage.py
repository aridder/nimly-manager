"""Persistent, credential-free storage for Nimly Manager."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .slots import FingerprintSlotRegistry

STORAGE_KEY = f"{DOMAIN}.slots"
STORAGE_VERSION = 1


class NimlySlotStorage:
    """Own persistent slot registries for all configured locks."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)
        self._stored_entries: dict[str, object] = {}
        self._registries: dict[str, FingerprintSlotRegistry] = {}

    async def async_load(self) -> None:
        """Load safe slot metadata."""

        data = await self._store.async_load()
        if not isinstance(data, dict):
            return
        entries = data.get("entries")
        if isinstance(entries, dict):
            self._stored_entries = dict(entries)

    def registry_for(self, entry_id: str) -> FingerprintSlotRegistry:
        """Return one live registry, restoring it on first use."""

        if entry_id not in self._registries:
            raw_entry = self._stored_entries.get(entry_id)
            raw_slots = raw_entry.get("slots") if isinstance(raw_entry, dict) else None
            self._registries[entry_id] = FingerprintSlotRegistry.from_storage(
                raw_slots,
                on_change=self._schedule_save,
            )
        return self._registries[entry_id]

    async def async_remove_entry(self, entry_id: str) -> None:
        """Remove persisted metadata when the config entry is deleted."""

        self._registries.pop(entry_id, None)
        self._stored_entries.pop(entry_id, None)
        await self._store.async_save(self._serialize())

    @callback
    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._serialize, delay=1)

    @callback
    def _serialize(self) -> dict[str, Any]:
        entries = {
            entry_id: {"slots": registry.as_list()}
            for entry_id, registry in self._registries.items()
        }
        for entry_id, value in self._stored_entries.items():
            entries.setdefault(entry_id, value)
        return {"entries": entries}
