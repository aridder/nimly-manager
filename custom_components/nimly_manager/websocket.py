"""Admin-only WebSocket API for the Nimly Manager panel."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_PERSON_ID,
    ATTR_PERSON_NAME,
    ATTR_SESSION_ID,
    ATTR_SLOT,
    DATA_RUNTIMES,
    DOMAIN,
)
from .fingerprint_enrollment import (
    FINGERPRINT_SLOT_MAX,
    FINGERPRINT_SLOT_MIN,
    FingerprintEnrollmentError,
)
from .runtime import NimlyLockRuntime, service_response
from .services import async_fire_enrollment_state

WS_STATE = f"{DOMAIN}/state"
WS_START = f"{DOMAIN}/enrollment/start"
WS_CONFIRM = f"{DOMAIN}/enrollment/confirm"
WS_CANCEL = f"{DOMAIN}/enrollment/cancel"


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


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register panel commands once."""

    for command in (
        websocket_state,
        websocket_start,
        websocket_confirm,
        websocket_cancel,
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
    return {
        "config_entry_id": entry_id,
        "title": entry.title if entry is not None else runtime.topic,
        **runtime.public_state(now=now),
    }
