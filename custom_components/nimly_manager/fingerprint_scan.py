"""State of one BLE-started fingerprint scan, verified over Zigbee afterwards.

Pure domain object, no Home Assistant imports. It replaces only the "go to
the lock and do the master-finger sequence" step of the guided enrollment:
Home Assistant sends ``FingerprintScan`` to a BLE slot (150–199), the person
puts the finger on the sensor, and the existing Zigbee verification confirms
the result. The lock answers *after* the scan is done, so the "finger on
NOW" moment is the instant the command is written, not when it is answered.

Biometric material never enters this model, and neither does the owner key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from .fingerprint_enrollment import FingerprintEnrollmentError, _require_timezone
from .nimly_ble.protocol import FINGERPRINT_SLOT_MAX as BLE_SLOT_MAX
from .nimly_ble.protocol import FINGERPRINT_SLOT_MIN as BLE_SLOT_MIN

__all__ = [
    "BLE_SLOT_MAX",
    "BLE_SLOT_MIN",
    "BleFingerprintScan",
    "ScanState",
]


class ScanState(StrEnum):
    """States of a BLE-started scan."""

    CONNECTING = "connecting"
    SCANNING = "scanning"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


ACTIVE_SCAN_STATES = frozenset(
    {
        ScanState.CONNECTING,
        ScanState.SCANNING,
        ScanState.AWAITING_VERIFICATION,
    }
)
TERMINAL_SCAN_STATES = frozenset(
    {
        ScanState.VERIFIED,
        ScanState.FAILED,
        ScanState.CANCELLED,
        ScanState.EXPIRED,
    }
)


@dataclass(slots=True)
class BleFingerprintScan:
    """One scan request: who, which BLE slot, and how far it got."""

    session_id: str
    person_id: str
    person_name: str
    ble_slot: int
    started_at: datetime
    expires_at: datetime
    state: ScanState = ScanState.CONNECTING
    finger_prompt_at: datetime | None = None
    scanned_at: datetime | None = None
    scan_status: str | None = None
    reported_slot: int | None = None
    response_seconds: float | None = None
    model: str | None = None
    firmware: str | None = None
    zigbee_slot: int | None = None
    verified_at: datetime | None = None
    enrollment_session_id: str | None = None
    error: str | None = None

    @classmethod
    def start(
        cls,
        *,
        person_id: str,
        person_name: str,
        ble_slot: int,
        now: datetime,
        ttl: timedelta = timedelta(minutes=15),
    ) -> BleFingerprintScan:
        """Create a time-limited scan; the connection attempt starts now."""

        person_id = person_id.strip()
        person_name = person_name.strip()
        if not person_id:
            raise FingerprintEnrollmentError("person_id kan ikke være tom")
        if not person_name:
            raise FingerprintEnrollmentError("person_name kan ikke være tom")
        if len(person_name) > 100:
            raise FingerprintEnrollmentError("person_name kan ikke overstige 100 tegn")
        if not BLE_SLOT_MIN <= ble_slot <= BLE_SLOT_MAX:
            raise FingerprintEnrollmentError(
                f"BLE-slot må være {BLE_SLOT_MIN}–{BLE_SLOT_MAX}"
            )
        _require_timezone(now)
        if not timedelta(minutes=1) <= ttl <= timedelta(hours=1):
            raise FingerprintEnrollmentError("ttl må være mellom 1 og 60 minutter")
        return cls(
            session_id=str(uuid4()),
            person_id=person_id,
            person_name=person_name,
            ble_slot=ble_slot,
            started_at=now,
            expires_at=now + ttl,
        )

    @property
    def is_active(self) -> bool:
        return self.state in ACTIVE_SCAN_STATES

    @property
    def armed_for_verification(self) -> bool:
        """Only a scan the lock answered ``ok`` may claim the next unlock."""

        return self.state is ScanState.AWAITING_VERIFICATION

    def mark_scanning(self, *, now: datetime) -> None:
        """The command is being written: finger on the sensor NOW."""

        self._expire(now)
        if self.state is not ScanState.CONNECTING:
            raise FingerprintEnrollmentError(
                f"kan ikke starte skanning fra {self.state}"
            )
        self.state = ScanState.SCANNING
        self.finger_prompt_at = now

    def mark_scanned(
        self,
        *,
        now: datetime,
        scan_status: str,
        reported_slot: int | None,
        response_seconds: float | None,
        model: str | None = None,
        firmware: str | None = None,
    ) -> None:
        """The lock answered. ``ok`` arms Zigbee verification; anything else fails."""

        self._expire(now)
        if self.state is not ScanState.SCANNING:
            raise FingerprintEnrollmentError(
                f"kan ikke avslutte skanning fra {self.state}"
            )
        self.scanned_at = now
        self.scan_status = scan_status
        self.reported_slot = reported_slot
        self.response_seconds = response_seconds
        self.model = model
        self.firmware = firmware
        if scan_status == "ok":
            self.state = ScanState.AWAITING_VERIFICATION
        else:
            self.state = ScanState.FAILED
            self.error = f"låsen svarte {scan_status}"

    def fail(self, *, now: datetime, error: str) -> None:
        """Abort from any active state with a user-facing reason (never a key)."""

        self._expire(now)
        if self.state in TERMINAL_SCAN_STATES:
            return
        self.state = ScanState.FAILED
        self.error = error

    def cancel(self, *, now: datetime) -> None:
        """Local cancel. The lock may still finish a scan already started."""

        self._expire(now)
        if self.state in TERMINAL_SCAN_STATES:
            raise FingerprintEnrollmentError(f"kan ikke avbryte fra {self.state}")
        self.state = ScanState.CANCELLED

    def observe_verified(
        self,
        *,
        now: datetime,
        zigbee_slot: int,
        enrollment_session_id: str,
    ) -> None:
        """Zigbee saw the first unlock with the new finger; record the pairing."""

        self._expire(now)
        if self.state is not ScanState.AWAITING_VERIFICATION:
            raise FingerprintEnrollmentError(f"kan ikke verifisere fra {self.state}")
        self.state = ScanState.VERIFIED
        self.zigbee_slot = zigbee_slot
        self.verified_at = now
        self.enrollment_session_id = enrollment_session_id

    def refresh(self, *, now: datetime) -> ScanState:
        self._expire(now)
        return self.state

    def as_public_dict(self) -> dict[str, object]:
        """UI-safe view. Contains no key material and no biometrics."""

        return {
            "session_id": self.session_id,
            "person_id": self.person_id,
            "person_name": self.person_name,
            "ble_slot": self.ble_slot,
            "state": self.state.value,
            "started_at": self.started_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "finger_prompt_at": _iso(self.finger_prompt_at),
            "scanned_at": _iso(self.scanned_at),
            "scan_status": self.scan_status,
            "reported_slot": self.reported_slot,
            "response_seconds": self.response_seconds,
            "model": self.model,
            "firmware": self.firmware,
            "zigbee_slot": self.zigbee_slot,
            "verified_at": _iso(self.verified_at),
            "enrollment_session_id": self.enrollment_session_id,
            "error": self.error,
        }

    def _expire(self, now: datetime) -> None:
        _require_timezone(now)
        if self.state in ACTIVE_SCAN_STATES and now >= self.expires_at:
            self.state = ScanState.EXPIRED


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
