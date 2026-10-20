"""Credential-free runtime state for one Nimly lock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .fingerprint_enrollment import (
    FINGERPRINT_SLOT_MAX,
    FINGERPRINT_SLOT_MIN,
    FINGERPRINT_SOURCES,
    TERMINAL_STATES,
    FingerprintEnrollment,
    FingerprintEnrollmentError,
)
from .fingerprint_scan import BleFingerprintScan
from .slots import FingerprintSlotRegistry

LOCKED = "locked"
UNLOCKED = "unlocked"


@dataclass(frozen=True, slots=True)
class FingerprintVerification:
    """Safe verification result emitted to Home Assistant."""

    session: FingerprintEnrollment
    source: str
    user_slot: int
    ble_slot: int | None = None

    def as_event_data(self) -> dict[str, object]:
        """Return event data without credentials or raw MQTT content."""

        return {
            **self.session.as_public_dict(),
            "source": self.source,
            "user_id": self.user_slot,
            "ble_slot": self.ble_slot,
        }


class NimlyLockRuntime:
    """Track only the state needed to verify an enrollment safely."""

    def __init__(
        self,
        *,
        topic: str,
        slots: FingerprintSlotRegistry | None = None,
    ) -> None:
        self.topic = topic
        self.lock_state: str | None = None
        self.last_mqtt_at: datetime | None = None
        self.enrollment: FingerprintEnrollment | None = None
        self.scan: BleFingerprintScan | None = None
        self.slots = slots or FingerprintSlotRegistry()

    def start_enrollment(
        self,
        *,
        person_id: str,
        person_name: str,
        slot: int,
        now: datetime,
    ) -> FingerprintEnrollment:
        """Start one session, refusing to replace an active workflow."""

        self._refuse_if_busy(now=now)
        if self.slots.is_occupied(slot):
            raise FingerprintEnrollmentError(
                f"fingerprint-slot {slot:03d} er allerede bekreftet opptatt"
            )
        self.enrollment = FingerprintEnrollment.start(
            person_id=person_id,
            person_name=person_name,
            slot=slot,
            now=now,
        )
        return self.enrollment

    def confirm_enrollment(
        self, *, session_id: str, now: datetime
    ) -> FingerprintEnrollment:
        """Confirm local programming for the exact active session."""

        session = self._session(session_id)
        session.confirm_local_programming(now=now)
        return session

    def cancel_enrollment(
        self, *, session_id: str, now: datetime
    ) -> FingerprintEnrollment:
        """Cancel the exact active session."""

        session = self._session(session_id)
        session.cancel(now=now)
        return session

    def start_fingerprint_scan(
        self,
        *,
        person_id: str,
        person_name: str,
        ble_slot: int,
        now: datetime,
    ) -> BleFingerprintScan:
        """Start a BLE scan session; one workflow per lock at a time."""

        self._refuse_if_busy(now=now)
        if ble_slot in self.slots.used_ble_slots():
            raise FingerprintEnrollmentError(
                f"BLE-slot {ble_slot} er allerede brukt for en verifisert finger"
            )
        self.scan = BleFingerprintScan.start(
            person_id=person_id,
            person_name=person_name,
            ble_slot=ble_slot,
            now=now,
        )
        return self.scan

    def cancel_fingerprint_scan(
        self, *, session_id: str, now: datetime
    ) -> BleFingerprintScan:
        """Cancel the exact active scan; the caller stops the BLE task."""

        scan = self._scan(session_id)
        scan.cancel(now=now)
        return scan

    def observe_mqtt_state(
        self, payload: dict[str, Any], *, now: datetime
    ) -> FingerprintVerification | None:
        """Observe a Z2M state without retaining its credential-bearing payload."""

        current_state = _lock_state(payload)
        self.last_mqtt_at = now
        if current_state is None:
            return None

        previous_state = self.lock_state
        self.lock_state = current_state
        if previous_state != LOCKED or current_state != UNLOCKED:
            return None

        source = _text(payload.get("last_unlock_source"))
        user_slot = _slot(payload.get("last_unlock_user"))
        if source is None or user_slot is None:
            return None
        is_fingerprint = source.lower() in FINGERPRINT_SOURCES
        was_known = self.slots.is_occupied(user_slot)
        if is_fingerprint:
            try:
                self.slots.observe(slot=user_slot, now=now)
            except ValueError:
                return None

        if is_fingerprint and self._scan_claims(
            user_slot, was_known=was_known, now=now
        ):
            return self._verify_scan(source=source, user_slot=user_slot, now=now)

        session = self.enrollment
        if session is None:
            return None
        if not session.observe_unlock(source=source, user_slot=user_slot, now=now):
            return None
        self.slots.verify(
            slot=user_slot,
            person_id=session.person_id,
            person_name=session.person_name,
            now=now,
        )
        return FingerprintVerification(
            session=session,
            source=source.lower(),
            user_slot=user_slot,
        )

    def _scan_claims(self, user_slot: int, *, was_known: bool, now: datetime) -> bool:
        """Whether an armed BLE scan takes this fingerprint unlock as its own.

        The Zigbee slot of a BLE-enrolled finger is unknown in advance (BLE
        150 reported as Zigbee 11 on 2026-10-20), so the first fingerprint
        unlock after an ``ok`` scan is taken — unless it comes from a slot
        the registry already knew, which means some other finger was used.
        The regular keypad enrollment keeps its exact-slot rule untouched.
        """

        scan = self.scan
        if scan is None:
            return False
        scan.refresh(now=now)
        if not scan.armed_for_verification:
            return False
        if was_known:
            return False
        return FINGERPRINT_SLOT_MIN <= user_slot <= FINGERPRINT_SLOT_MAX

    def _verify_scan(
        self, *, source: str, user_slot: int, now: datetime
    ) -> FingerprintVerification | None:
        """Run the unchanged enrollment verification for the slot Zigbee named."""

        scan = self.scan
        assert scan is not None
        session = FingerprintEnrollment.start(
            person_id=scan.person_id,
            person_name=scan.person_name,
            slot=user_slot,
            now=now,
        )
        session.confirm_local_programming(now=now)
        if not session.observe_unlock(source=source, user_slot=user_slot, now=now):
            return None
        self.slots.verify(
            slot=user_slot,
            person_id=scan.person_id,
            person_name=scan.person_name,
            now=now,
            ble_slot=scan.ble_slot,
        )
        scan.observe_verified(
            now=now, zigbee_slot=user_slot, enrollment_session_id=session.session_id
        )
        self.enrollment = session
        return FingerprintVerification(
            session=session,
            source=source.lower(),
            user_slot=user_slot,
            ble_slot=scan.ble_slot,
        )

    def diagnostics(self, *, now: datetime) -> dict[str, object]:
        """Return a minimal diagnostic snapshot without raw MQTT state."""

        enrollment: dict[str, object] | None = None
        if self.enrollment is not None:
            self.enrollment.refresh(now=now)
            enrollment = self.enrollment.as_public_dict()
        scan: dict[str, object] | None = None
        if self.scan is not None:
            self.scan.refresh(now=now)
            scan = self.scan.as_public_dict()
        return {
            "state_topic": self.topic,
            "lock_state": self.lock_state,
            "last_mqtt_at": (
                self.last_mqtt_at.isoformat() if self.last_mqtt_at is not None else None
            ),
            "fingerprint_enrollment": enrollment,
            "fingerprint_scan": scan,
            "fingerprint_slot_counts": self.slots.diagnostics(),
        }

    def public_state(self, *, now: datetime) -> dict[str, object]:
        """Return admin-visible state for the Nimly Manager panel."""

        enrollment: dict[str, object] | None = None
        instructions: list[str] = []
        if self.enrollment is not None:
            self.enrollment.refresh(now=now)
            enrollment = self.enrollment.as_public_dict()
            instructions = list(self.enrollment.instructions)
        scan: dict[str, object] | None = None
        if self.scan is not None:
            self.scan.refresh(now=now)
            scan = self.scan.as_public_dict()
        return {
            "state_topic": self.topic,
            "lock_state": self.lock_state,
            "last_mqtt_at": (
                self.last_mqtt_at.isoformat() if self.last_mqtt_at is not None else None
            ),
            "enrollment": enrollment,
            "instructions": instructions,
            "scan": scan,
            "used_ble_slots": self.slots.used_ble_slots(),
            "slots": self.slots.as_list(),
        }

    def _refuse_if_busy(self, *, now: datetime) -> None:
        if self.enrollment is not None:
            state = self.enrollment.refresh(now=now)
            if state not in TERMINAL_STATES:
                raise FingerprintEnrollmentError(
                    "låsen har allerede en aktiv fingerprint-enrollment"
                )
        if self.scan is not None:
            self.scan.refresh(now=now)
            if self.scan.is_active:
                raise FingerprintEnrollmentError(
                    "låsen har allerede en aktiv BLE-skanning"
                )

    def _session(self, session_id: str) -> FingerprintEnrollment:
        session_id = session_id.strip()
        if self.enrollment is None or self.enrollment.session_id != session_id:
            raise FingerprintEnrollmentError("ukjent eller utløpt enrollment-session")
        return self.enrollment

    def _scan(self, session_id: str) -> BleFingerprintScan:
        session_id = session_id.strip()
        if self.scan is None or self.scan.session_id != session_id:
            raise FingerprintEnrollmentError("ukjent eller utløpt skanne-session")
        return self.scan


def _lock_state(payload: dict[str, Any]) -> str | None:
    raw = payload.get("state", payload.get("lock_state"))
    value = _text(raw)
    if value is None:
        return None
    return {
        "lock": LOCKED,
        "locked": LOCKED,
        "unlock": UNLOCKED,
        "unlocked": UNLOCKED,
    }.get(value.lower())


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value else None


def _slot(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def service_response(session: FingerprintEnrollment) -> dict[str, object]:
    """Build a JSON-serializable action response."""

    return {
        "enrollment": session.as_public_dict(),
        "instructions": list(session.instructions),
    }
