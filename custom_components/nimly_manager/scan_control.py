"""Shared entry points for starting and cancelling a BLE scan.

Used by both the actions and the panel's WebSocket commands so the gates
live in one place: loaded entry, imported owner key, configured BLE address,
explicit at-the-lock confirmation, one workflow per lock.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from homeassistant.core import HomeAssistant, callback

from .ble_scan import FingerprintScanCoordinator
from .const import (
    CONF_BLE_ADDRESS,
    DATA_OWNER_STORE,
    DATA_RUNTIMES,
    DATA_SCAN_COORDINATOR,
    DOMAIN,
)
from .fingerprint_enrollment import FingerprintEnrollmentError
from .fingerprint_scan import BleFingerprintScan
from .owner_store import NimlyOwnerKeyStore
from .runtime import NimlyLockRuntime


async def async_start_scan(
    hass: HomeAssistant,
    *,
    entry_id: str,
    person_id: str | None,
    person_name: str,
    ble_slot: int,
    at_the_lock: bool,
) -> BleFingerprintScan:
    """Validate every gate, then hand the scan to the background task."""

    runtime = _runtime(hass, entry_id)
    if not at_the_lock:
        raise FingerprintEnrollmentError(
            "bekreft at du står ved låsen: fingeren må på sensoren idet kommandoen sendes"
        )
    entry = hass.config_entries.async_get_entry(entry_id)
    address = entry.options.get(CONF_BLE_ADDRESS) if entry is not None else None
    if not address:
        raise FingerprintEnrollmentError(
            "låsen har ingen BLE-adresse; importer eiernøkkelen under Konfigurer"
        )
    store: NimlyOwnerKeyStore = hass.data[DOMAIN][DATA_OWNER_STORE]
    record = store.get(entry_id)
    if record is None:
        raise FingerprintEnrollmentError(
            "ingen eiernøkkel er importert for denne låsen (Konfigurer → importer)"
        )
    coordinator: FingerprintScanCoordinator = hass.data[DOMAIN][DATA_SCAN_COORDINATOR]
    scan = runtime.start_fingerprint_scan(
        person_id=person_id or f"person-{uuid4()}",
        person_name=person_name,
        ble_slot=ble_slot,
        now=datetime.now(UTC),
    )
    try:
        coordinator.async_start(
            entry_id=entry_id,
            runtime=runtime,
            scan=scan,
            record=record,
            address=address,
            title=entry.title if entry is not None else runtime.topic,
        )
    except RuntimeError as error:
        scan.fail(now=datetime.now(UTC), error=str(error))
        raise FingerprintEnrollmentError(str(error)) from error
    return scan


@callback
def async_cancel_scan(
    hass: HomeAssistant, *, entry_id: str, session_id: str
) -> BleFingerprintScan:
    runtime = _runtime(hass, entry_id)
    scan = runtime.cancel_fingerprint_scan(session_id=session_id, now=datetime.now(UTC))
    coordinator: FingerprintScanCoordinator = hass.data[DOMAIN][DATA_SCAN_COORDINATOR]
    coordinator.async_cancel(entry_id)
    coordinator.async_fire_state(entry_id, scan)
    return scan


def _runtime(hass: HomeAssistant, entry_id: str) -> NimlyLockRuntime:
    runtimes: dict[str, NimlyLockRuntime] = hass.data[DOMAIN][DATA_RUNTIMES]
    if (runtime := runtimes.get(entry_id)) is None:
        raise FingerprintEnrollmentError(
            "Nimly Manager-oppsettet finnes ikke eller er ikke lastet"
        )
    return runtime
