"""Credential-free runtime state for one Nimly lock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .fingerprint_enrollment import (
    TERMINAL_STATES,
    FingerprintEnrollment,
    FingerprintEnrollmentError,
)

LOCKED = "locked"
UNLOCKED = "unlocked"


@dataclass(frozen=True, slots=True)
class FingerprintVerification:
    """Safe verification result emitted to Home Assistant."""

    session: FingerprintEnrollment
    source: str
    user_slot: int

    def as_event_data(self) -> dict[str, object]:
        """Return event data without credentials or raw MQTT content."""

        return {
            **self.session.as_public_dict(),
            "source": self.source,
            "user_id": self.user_slot,
        }


class NimlyLockRuntime:
    """Track only the state needed to verify an enrollment safely."""

    def __init__(self, *, topic: str) -> None:
        self.topic = topic
        self.lock_state: str | None = None
        self.enrollment: FingerprintEnrollment | None = None

    def start_enrollment(
        self,
        *,
        person_id: str,
        person_name: str,
        slot: int,
        now: datetime,
    ) -> FingerprintEnrollment:
        """Start one session, refusing to replace an active workflow."""

        if self.enrollment is not None:
            state = self.enrollment.refresh(now=now)
            if state not in TERMINAL_STATES:
                raise FingerprintEnrollmentError(
                    "låsen har allerede en aktiv fingerprint-enrollment"
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

    def observe_mqtt_state(
        self, payload: dict[str, Any], *, now: datetime
    ) -> FingerprintVerification | None:
        """Observe a Z2M state without retaining its credential-bearing payload."""

        current_state = _lock_state(payload)
        if current_state is None:
            return None

        previous_state = self.lock_state
        self.lock_state = current_state
        if previous_state != LOCKED or current_state != UNLOCKED:
            return None

        session = self.enrollment
        if session is None:
            return None

        source = _text(payload.get("last_unlock_source"))
        user_slot = _slot(payload.get("last_unlock_user"))
        if source is None or user_slot is None:
            return None
        if not session.observe_unlock(source=source, user_slot=user_slot, now=now):
            return None
        return FingerprintVerification(
            session=session,
            source=source.lower(),
            user_slot=user_slot,
        )

    def diagnostics(self, *, now: datetime) -> dict[str, object]:
        """Return a minimal diagnostic snapshot without raw MQTT state."""

        enrollment: dict[str, object] | None = None
        if self.enrollment is not None:
            self.enrollment.refresh(now=now)
            enrollment = self.enrollment.as_public_dict()
        return {
            "state_topic": self.topic,
            "lock_state": self.lock_state,
            "fingerprint_enrollment": enrollment,
        }

    def _session(self, session_id: str) -> FingerprintEnrollment:
        session_id = session_id.strip()
        if self.enrollment is None or self.enrollment.session_id != session_id:
            raise FingerprintEnrollmentError("ukjent eller utløpt enrollment-session")
        return self.enrollment


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
