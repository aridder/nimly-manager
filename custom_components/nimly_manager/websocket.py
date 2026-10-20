"""Admin-only WebSocket API for the Nimly Manager panel."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .ble_setup import (
    BleSetupError,
    async_apply_ble_setup,
    discovered_nimly_locks,
    parse_owner_record,
)
from .ble_transport import ble_status
from .const import (
    ATTR_AT_THE_LOCK,
    ATTR_BLE_SLOT,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_PERSON_ID,
    ATTR_PERSON_NAME,
    ATTR_SESSION_ID,
    ATTR_SLOT,
    CONF_BLE_ADDRESS,
    DATA_OWNER_STORE,
    DATA_RUNTIMES,
    DOMAIN,
    OPTION_OWNER_NAME,
)
from .fingerprint_enrollment import (
    FINGERPRINT_SLOT_MAX,
    FINGERPRINT_SLOT_MIN,
    FingerprintEnrollmentError,
)
from .fingerprint_scan import BLE_SLOT_MAX, BLE_SLOT_MIN
from .owner_store import NimlyOwnerKeyStore
from .runtime import NimlyLockRuntime, service_response
from .scan_control import async_cancel_scan, async_start_scan
from .services import async_fire_enrollment_state, scan_response

WS_STATE = f"{DOMAIN}/state"
WS_START = f"{DOMAIN}/enrollment/start"
WS_CONFIRM = f"{DOMAIN}/enrollment/confirm"
WS_CANCEL = f"{DOMAIN}/enrollment/cancel"
WS_SCAN_START = f"{DOMAIN}/fingerprint_scan/start"
WS_SCAN_CANCEL = f"{DOMAIN}/fingerprint_scan/cancel"
WS_BLE_CANDIDATES = f"{DOMAIN}/ble/candidates"
WS_BLE_SETUP = f"{DOMAIN}/ble/setup"


@websocket_api.websocket_command(
    {
        "type": WS_STATE,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)
@websocket_api.require_admin
@callback
def websocket_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return panel state for one or all configured locks."""

    entry_id = msg.get(ATTR_CONFIG_ENTRY_ID)
    runtimes = _runtimes(hass)
    if entry_id is not None and entry_id not in runtimes:
        connection.send_error(msg["id"], "entry_not_loaded", "Låsen er ikke lastet")
        return
    selected = (
        [(entry_id, runtimes[entry_id])]
        if entry_id is not None
        else list(runtimes.items())
    )
    now = datetime.now(UTC)
    connection.send_result(
        msg["id"],
        {
            "slot_min": FINGERPRINT_SLOT_MIN,
            "slot_max": FINGERPRINT_SLOT_MAX,
            "ble_slot_min": BLE_SLOT_MIN,
            "ble_slot_max": BLE_SLOT_MAX,
            "entries": [
                _entry_state(hass, current_entry_id, runtime, now=now)
                for current_entry_id, runtime in selected
            ],
        },
    )


@websocket_api.websocket_command(
    {
        "type": WS_START,
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_PERSON_ID): cv.string,
        vol.Required(ATTR_PERSON_NAME): cv.string,
        vol.Required(ATTR_SLOT): vol.All(
            vol.Coerce(int),
            vol.Range(min=FINGERPRINT_SLOT_MIN, max=FINGERPRINT_SLOT_MAX),
        ),
    }
)
@websocket_api.require_admin
@callback
def websocket_start(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Start a guided local enrollment from the panel."""

    runtime = _runtime_or_error(hass, connection, msg)
    if runtime is None:
        return
    try:
        session = runtime.start_enrollment(
            person_id=msg.get(ATTR_PERSON_ID) or f"person-{uuid4()}",
            person_name=msg[ATTR_PERSON_NAME],
            slot=msg[ATTR_SLOT],
            now=datetime.now(UTC),
        )
    except FingerprintEnrollmentError as err:
        connection.send_error(msg["id"], "invalid_enrollment", str(err))
        return
    async_fire_enrollment_state(hass, msg[ATTR_CONFIG_ENTRY_ID], session)
    connection.send_result(msg["id"], service_response(session))


@websocket_api.websocket_command(
    {
        "type": WS_CONFIRM,
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SESSION_ID): cv.string,
    }
)
@websocket_api.require_admin
@callback
def websocket_confirm(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Confirm local programming for the exact active session."""

    runtime = _runtime_or_error(hass, connection, msg)
    if runtime is None:
        return
    try:
        session = runtime.confirm_enrollment(
            session_id=msg[ATTR_SESSION_ID],
            now=datetime.now(UTC),
        )
    except FingerprintEnrollmentError as err:
        connection.send_error(msg["id"], "invalid_enrollment", str(err))
        return
    async_fire_enrollment_state(hass, msg[ATTR_CONFIG_ENTRY_ID], session)
    connection.send_result(msg["id"], service_response(session))


@websocket_api.websocket_command(
    {
        "type": WS_CANCEL,
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SESSION_ID): cv.string,
    }
)
@websocket_api.require_admin
@callback
def websocket_cancel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Cancel only the exact active enrollment session."""

    runtime = _runtime_or_error(hass, connection, msg)
    if runtime is None:
        return
    try:
        session = runtime.cancel_enrollment(
            session_id=msg[ATTR_SESSION_ID],
            now=datetime.now(UTC),
        )
    except FingerprintEnrollmentError as err:
        connection.send_error(msg["id"], "invalid_enrollment", str(err))
        return
    async_fire_enrollment_state(hass, msg[ATTR_CONFIG_ENTRY_ID], session)
    connection.send_result(msg["id"], service_response(session))


@websocket_api.websocket_command(
    {
        "type": WS_SCAN_START,
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_PERSON_ID): cv.string,
        vol.Required(ATTR_PERSON_NAME): cv.string,
        vol.Required(ATTR_BLE_SLOT): vol.All(
            vol.Coerce(int),
            vol.Range(min=BLE_SLOT_MIN, max=BLE_SLOT_MAX),
        ),
        vol.Required(ATTR_AT_THE_LOCK): cv.boolean,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_scan_start(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Start a BLE fingerprint scan from the panel; returns before the lock answers."""

    if _runtime_or_error(hass, connection, msg) is None:
        return
    try:
        scan = await async_start_scan(
            hass,
            entry_id=msg[ATTR_CONFIG_ENTRY_ID],
            person_id=msg.get(ATTR_PERSON_ID),
            person_name=msg[ATTR_PERSON_NAME],
            ble_slot=msg[ATTR_BLE_SLOT],
            at_the_lock=msg[ATTR_AT_THE_LOCK],
        )
    except FingerprintEnrollmentError as err:
        connection.send_error(msg["id"], "invalid_scan", str(err))
        return
    connection.send_result(msg["id"], scan_response(scan))


@websocket_api.websocket_command(
    {
        "type": WS_SCAN_CANCEL,
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SESSION_ID): cv.string,
    }
)
@websocket_api.require_admin
@callback
def websocket_scan_cancel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Cancel the exact active BLE scan."""

    if _runtime_or_error(hass, connection, msg) is None:
        return
    try:
        scan = async_cancel_scan(
            hass,
            entry_id=msg[ATTR_CONFIG_ENTRY_ID],
            session_id=msg[ATTR_SESSION_ID],
        )
    except FingerprintEnrollmentError as err:
        connection.send_error(msg["id"], "invalid_scan", str(err))
        return
    connection.send_result(msg["id"], scan_response(scan))


@websocket_api.websocket_command({"type": WS_BLE_CANDIDATES})
@websocket_api.require_admin
@callback
def websocket_ble_candidates(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Nimly advertisements HA can connect to, for the address picker."""

    connection.send_result(msg["id"], {"locks": discovered_nimly_locks(hass)})


@websocket_api.websocket_command(
    {
        "type": WS_BLE_SETUP,
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(CONF_BLE_ADDRESS): cv.string,
        vol.Optional("owner_record"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_ble_setup(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Import the owner key and BLE address from the panel. Never echoes the key."""

    entry = hass.config_entries.async_get_entry(msg[ATTR_CONFIG_ENTRY_ID])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "entry_not_loaded", "Låsen er ikke lastet")
        return
    try:
        record = parse_owner_record(msg.get("owner_record"))
        options = await async_apply_ble_setup(
            hass, entry, address=msg[CONF_BLE_ADDRESS], record=record
        )
    except BleSetupError as err:
        connection.send_error(msg["id"], "invalid_ble_setup", str(err))
        return
    hass.config_entries.async_update_entry(entry, options=options)
    store: NimlyOwnerKeyStore = hass.data[DOMAIN][DATA_OWNER_STORE]
    connection.send_result(
        msg["id"],
        {
            "address": options[CONF_BLE_ADDRESS],
            "owner_key_imported": store.has(entry.entry_id),
        },
    )


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register panel commands once."""

    for command in (
        websocket_state,
        websocket_start,
        websocket_confirm,
        websocket_cancel,
        websocket_scan_start,
        websocket_scan_cancel,
        websocket_ble_candidates,
        websocket_ble_setup,
    ):
        websocket_api.async_register_command(hass, command)


def _runtimes(hass: HomeAssistant) -> dict[str, NimlyLockRuntime]:
    return hass.data[DOMAIN][DATA_RUNTIMES]


def _runtime_or_error(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> NimlyLockRuntime | None:
    runtime = _runtimes(hass).get(msg[ATTR_CONFIG_ENTRY_ID])
    if runtime is None:
        connection.send_error(msg["id"], "entry_not_loaded", "Låsen er ikke lastet")
    return runtime


def _entry_state(
    hass: HomeAssistant,
    entry_id: str,
    runtime: NimlyLockRuntime,
    *,
    now: datetime,
) -> dict[str, object]:
    entry = hass.config_entries.async_get_entry(entry_id)
    store: NimlyOwnerKeyStore = hass.data[DOMAIN][DATA_OWNER_STORE]
    address = entry.options.get(CONF_BLE_ADDRESS) if entry is not None else None
    return {
        "config_entry_id": entry_id,
        "title": entry.title if entry is not None else runtime.topic,
        **runtime.public_state(now=now),
        "ble": {
            **ble_status(hass, address),
            "owner_key_imported": store.has(entry_id),
            "owner_name": (
                entry.options.get(OPTION_OWNER_NAME) if entry is not None else None
            ),
        },
    }
