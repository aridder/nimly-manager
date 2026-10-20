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
    ATTR_AT_THE_LOCK,
    ATTR_BLE_SLOT,
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
    SERVICE_CANCEL_FINGERPRINT_SCAN,
    SERVICE_CONFIRM_FINGERPRINT_ENROLLMENT,
    SERVICE_START_FINGERPRINT_ENROLLMENT,
    SERVICE_START_FINGERPRINT_SCAN,
)
from .fingerprint_enrollment import (
    FINGERPRINT_SLOT_MAX,
    FINGERPRINT_SLOT_MIN,
    FingerprintEnrollment,
    FingerprintEnrollmentError,
)
from .fingerprint_scan import BLE_SLOT_MAX, BLE_SLOT_MIN, BleFingerprintScan
from .runtime import NimlyLockRuntime, service_response
from .scan_control import async_cancel_scan, async_start_scan

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
SCAN_SCHEMA = ENTRY_SCHEMA.extend(
    {
        vol.Optional(ATTR_PERSON_ID): cv.string,
        vol.Required(ATTR_PERSON_NAME): cv.string,
        vol.Required(ATTR_BLE_SLOT): vol.All(
            vol.Coerce(int), vol.Range(min=BLE_SLOT_MIN, max=BLE_SLOT_MAX)
        ),
        vol.Required(ATTR_AT_THE_LOCK): cv.boolean,
    }
)


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
        async_fire_enrollment_state(hass, call.data[ATTR_CONFIG_ENTRY_ID], session)
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
        async_fire_enrollment_state(hass, call.data[ATTR_CONFIG_ENTRY_ID], session)
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
        async_fire_enrollment_state(hass, call.data[ATTR_CONFIG_ENTRY_ID], session)
        return service_response(session) if call.return_response else None

    async def start_scan(call: ServiceCall) -> ServiceResponse | None:
        _runtime(hass, call)  # fail early on an unloaded entry
        try:
            scan = await async_start_scan(
                hass,
                entry_id=call.data[ATTR_CONFIG_ENTRY_ID],
                person_id=call.data.get(ATTR_PERSON_ID),
                person_name=call.data[ATTR_PERSON_NAME],
                ble_slot=call.data[ATTR_BLE_SLOT],
                at_the_lock=call.data[ATTR_AT_THE_LOCK],
            )
        except FingerprintEnrollmentError as err:
            raise ServiceValidationError(str(err)) from err
        return scan_response(scan) if call.return_response else None

    async def cancel_scan(call: ServiceCall) -> ServiceResponse | None:
        _runtime(hass, call)
        try:
            scan = async_cancel_scan(
                hass,
                entry_id=call.data[ATTR_CONFIG_ENTRY_ID],
                session_id=call.data[ATTR_SESSION_ID],
            )
        except FingerprintEnrollmentError as err:
            raise ServiceValidationError(str(err)) from err
        return scan_response(scan) if call.return_response else None

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_FINGERPRINT_SCAN,
        start_scan,
        schema=SCAN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_FINGERPRINT_SCAN,
        cancel_scan,
        schema=SESSION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
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


def async_fire_enrollment_state(
    hass: HomeAssistant,
    entry_id: str,
    session: FingerprintEnrollment,
) -> None:
    data: dict[str, Any] = {
        "config_entry_id": entry_id,
        **session.as_public_dict(),
    }
    hass.bus.async_fire(EVENT_FINGERPRINT_ENROLLMENT_STATE, data)


def scan_response(scan: BleFingerprintScan) -> dict[str, object]:
    """JSON-serializable action response for a BLE scan."""

    return {"scan": scan.as_public_dict()}
