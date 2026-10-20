"""Run one BLE fingerprint scan as a background task and publish its state.

The action returns at once with the session id; progress goes out as
``nimly_fingerprint_scan_state`` events and through the panel's state call.
Hard limits: the whole attempt (connect via proxy, handshake, auth, scan)
must finish within ``TOTAL_TIMEOUT``; a single command answer within
``RESPONSE_TIMEOUT`` (the lock answered FingerprintScan after 8.5 s on
2026-10-20). A local cancel stops the task; the lock may still finish a scan
that was already started.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .ble_transport import HomeAssistantTransport, LockNotVisibleError
from .const import EVENT_FINGERPRINT_SCAN_STATE
from .fingerprint_scan import BleFingerprintScan
from .nimly_ble import enrollment
from .nimly_ble.constants import parse_firmware
from .nimly_ble.keystore import OwnerRecord
from .nimly_ble.session import CommandFailed, Session, SessionError
from .runtime import NimlyLockRuntime

_LOGGER = logging.getLogger(__name__)

TOTAL_TIMEOUT = 90.0
RESPONSE_TIMEOUT = 30.0


class FingerprintScanCoordinator:
    """At most one running scan task per config entry."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @callback
    def async_start(
        self,
        *,
        entry_id: str,
        runtime: NimlyLockRuntime,
        scan: BleFingerprintScan,
        record: OwnerRecord,
        address: str,
        title: str,
    ) -> None:
        if (existing := self._tasks.get(entry_id)) is not None and not existing.done():
            raise RuntimeError("en BLE-skanning kjører allerede for denne låsen")
        self._tasks[entry_id] = self._hass.async_create_background_task(
            self._run(entry_id, runtime, scan, record, address, title),
            name=f"nimly_manager fingerprint scan {entry_id}",
        )
        self.async_fire_state(entry_id, scan)

    @callback
    def async_cancel(self, entry_id: str) -> None:
        task = self._tasks.pop(entry_id, None)
        if task is not None and not task.done():
            task.cancel()

    @callback
    def async_fire_state(self, entry_id: str, scan: BleFingerprintScan) -> None:
        data: dict[str, Any] = {"config_entry_id": entry_id, **scan.as_public_dict()}
        self._hass.bus.async_fire(EVENT_FINGERPRINT_SCAN_STATE, data)

    async def _run(
        self,
        entry_id: str,
        runtime: NimlyLockRuntime,
        scan: BleFingerprintScan,
        record: OwnerRecord,
        address: str,
        title: str,
    ) -> None:
        def now() -> datetime:
            return datetime.now(UTC)

        def finger_prompt() -> None:
            scan.mark_scanning(now=now())
            self.async_fire_state(entry_id, scan)

        try:
            async with asyncio.timeout(TOTAL_TIMEOUT):
                async with HomeAssistantTransport(
                    self._hass, address, name=title
                ) as transport:
                    firmware_text = await transport.read_software_revision()
                    firmware = parse_firmware(firmware_text)
                    if firmware is None:
                        raise enrollment.EnrollmentRefused(
                            f"kunne ikke tolke firmware {firmware_text!r}"
                        )
                    session = Session(
                        transport, firmware=firmware, timeout=RESPONSE_TIMEOUT
                    )
                    result = await enrollment.scan_fingerprint(
                        session,
                        record,
                        slot=scan.ble_slot,
                        firmware=firmware,
                        on_finger_prompt=finger_prompt,
                    )
            scan.mark_scanned(
                now=now(),
                scan_status=str(result["scan_status"]),
                reported_slot=_int_or_none(result.get("reported_slot")),
                response_seconds=_float_or_none(result.get("response_seconds")),
                model=str(result.get("model")),
                firmware=str(result.get("firmware")),
            )
        except asyncio.CancelledError:
            # Local cancel already moved the scan to CANCELLED; shutdown too.
            scan.fail(now=now(), error="avbrutt")
            raise
        except TimeoutError:
            scan.fail(now=now(), error="tidsavbrudd mot låsen")
        except LockNotVisibleError as error:
            scan.fail(now=now(), error=str(error))
        except enrollment.EnrollmentRefused as error:
            scan.fail(now=now(), error=f"nektet: {error}")
        except CommandFailed as error:
            scan.fail(now=now(), error=f"låsen avviste: {error}")
        except SessionError as error:
            scan.fail(now=now(), error=f"BLE-feil: {error}")
        except Exception as error:
            _LOGGER.exception("BLE-skanning feilet for %s", title)
            scan.fail(now=now(), error=f"uventet feil: {type(error).__name__}")
        finally:
            self._tasks.pop(entry_id, None)
            self.async_fire_state(entry_id, scan)


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
