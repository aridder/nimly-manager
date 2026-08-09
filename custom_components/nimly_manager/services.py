"""Actions for guided local fingerprint enrollment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_PERSON_ID,
    ATTR_PERSON_NAME,
    ATTR_SESSION_ID,
    ATTR_SLOT,
    DATA_RUNTIMES,
    DATA_SERVICES_REGISTERED,
    DOMAIN,
    EVENT_FINGERPRINT_ENROLLMENT_STATE,
    SERVICE_CANCEL_FINGERPRINT_ENROLLMENT,
    SERVICE_CONFIRM_FINGERPRINT_ENROLLMENT,
    SERVICE_START_FINGERPRINT_ENROLLMENT,
)
from .fingerprint_enrollment import (
    FINGERPRINT_SLOT_MAX,
    FINGERPRINT_SLOT_MIN,
    FingerprintEnrollment,
    FingerprintEnrollmentError,
)
from .runtime import NimlyLockRuntime, service_response

ENTRY_SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})
START_SCHEMA = ENTRY_SCHEMA.extend(
    {
        vol.Required(ATTR_PERSON_ID): cv.string,
        vol.Required(ATTR_PERSON_NAME): cv.string,
        vol.Required(ATTR_SLOT): vol.All(
            vol.Coerce(int),
            vol.Range(min=FINGERPRINT_SLOT_MIN, max=FINGERPRINT_SLOT_MAX),
        ),
    }
)
SESSION_SCHEMA = ENTRY_SCHEMA.extend({vol.Required(ATTR_SESSION_ID): cv.string})


def async_setup_services(hass: HomeAssistant) -> None:
    """Register actions even before a config entry is loaded."""

    domain_data = hass.data[DOMAIN]
    if domain_data.get(DATA_SERVICES_REGISTERED):
        return

    async def start(call: ServiceCall) -> ServiceResponse | None:
        runtime = _runtime(hass, call)
        try:
            session = runtime.start_enrollment(
                person_id=call.data[ATTR_PERSON_ID],
                person_name=call.data[ATTR_PERSON_NAME],
                slot=call.data[ATTR_SLOT],
                now=datetime.now(UTC),
            )
        except FingerprintEnrollmentError as err:
            raise ServiceValidationError(str(err)) from err
        _fire_state(hass, call.data[ATTR_CONFIG_ENTRY_ID], session)
        return service_response(session) if call.return_response else None

    async def confirm(call: ServiceCall) -> ServiceResponse | None:
        runtime = _runtime(hass, call)
        try:
            session = runtime.confirm_enrollment(
                session_id=call.data[ATTR_SESSION_ID],
                now=datetime.now(UTC),
            )
        except FingerprintEnrollmentError as err:
            raise ServiceValidationError(str(err)) from err
        _fire_state(hass, call.data[ATTR_CONFIG_ENTRY_ID], session)
        return service_response(session) if call.return_response else None

    async def cancel(call: ServiceCall) -> ServiceResponse | None:
        runtime = _runtime(hass, call)
        try:
            session = runtime.cancel_enrollment(
                session_id=call.data[ATTR_SESSION_ID],
                now=datetime.now(UTC),
            )
        except FingerprintEnrollmentError as err:
            raise ServiceValidationError(str(err)) from err
        _fire_state(hass, call.data[ATTR_CONFIG_ENTRY_ID], session)
        return service_response(session) if call.return_response else None

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_FINGERPRINT_ENROLLMENT,
        start,
        schema=START_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CONFIRM_FINGERPRINT_ENROLLMENT,
        confirm,
        schema=SESSION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_FINGERPRINT_ENROLLMENT,
        cancel,
        schema=SESSION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    domain_data[DATA_SERVICES_REGISTERED] = True


def _runtime(hass: HomeAssistant, call: ServiceCall) -> NimlyLockRuntime:
    entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
    runtimes: dict[str, NimlyLockRuntime] = hass.data[DOMAIN][DATA_RUNTIMES]
    if (runtime := runtimes.get(entry_id)) is None:
        raise ServiceValidationError(
            "Nimly Manager-oppsettet finnes ikke eller er ikke lastet"
        )
    return runtime


def _fire_state(
    hass: HomeAssistant,
    entry_id: str,
    session: FingerprintEnrollment,
) -> None:
    data: dict[str, Any] = {
        "config_entry_id": entry_id,
        **session.as_public_dict(),
    }
    hass.bus.async_fire(EVENT_FINGERPRINT_ENROLLMENT_STATE, data)
