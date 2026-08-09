"""Guided, local fingerprint enrollment with Zigbee event verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import uuid4

FINGERPRINT_SLOT_MIN = 3
FINGERPRINT_SLOT_MAX = 199
FINGERPRINT_SOURCES = frozenset({"fingerprint", "fingerprintsensor"})


class FingerprintEnrollmentError(ValueError):
    """Raised when an enrollment request or transition is invalid."""


class EnrollmentState(StrEnum):
    """States in the local enrollment workflow."""

    LOCAL_PROGRAMMING = "local_programming"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_STATES = frozenset(
    {
        EnrollmentState.VERIFIED,
        EnrollmentState.CANCELLED,
        EnrollmentState.EXPIRED,
    }
)


@dataclass(slots=True)
class FingerprintEnrollment:
    """One guided session; biometric material never enters this model."""

    session_id: str
    person_id: str
    person_name: str
    slot: int
    started_at: datetime
    expires_at: datetime
    state: EnrollmentState = EnrollmentState.LOCAL_PROGRAMMING
    verified_at: datetime | None = None

    @classmethod
    def start(
        cls,
        *,
        person_id: str,
        person_name: str,
        slot: int,
        now: datetime,
        ttl: timedelta = timedelta(minutes=15),
    ) -> FingerprintEnrollment:
        """Create a time-limited local enrollment session."""

        person_id = person_id.strip()
        person_name = person_name.strip()
        if not person_id:
            raise FingerprintEnrollmentError("person_id kan ikke være tom")
        if not person_name:
            raise FingerprintEnrollmentError("person_name kan ikke være tom")
        if len(person_name) > 100:
            raise FingerprintEnrollmentError("person_name kan ikke overstige 100 tegn")
        if not FINGERPRINT_SLOT_MIN <= slot <= FINGERPRINT_SLOT_MAX:
            raise FingerprintEnrollmentError(
                f"fingerprint-slot må være {FINGERPRINT_SLOT_MIN:03d}–"
                f"{FINGERPRINT_SLOT_MAX:03d}"
            )
        _require_timezone(now)
        if not timedelta(minutes=1) <= ttl <= timedelta(hours=1):
            raise FingerprintEnrollmentError("ttl må være mellom 1 og 60 minutter")
        return cls(
            session_id=str(uuid4()),
            person_id=person_id,
            person_name=person_name,
            slot=slot,
            started_at=now,
            expires_at=now + ttl,
        )

    @property
    def keypad_slot(self) -> str:
        """Return the three-digit slot entered on the lock."""

        return f"{self.slot:03d}"

    @property
    def instructions(self) -> tuple[str, ...]:
        """Return the verified local programming sequence."""

        return (
            "Vekk låsens berøringspanel.",
            "Trykk ###.",
            "Legg masterfinger på fingeravtrykksleseren.",
            f"Tast {self.keypad_slot}*.",
            "Følg låsens pip: legg på fingeren og løft etter pipet, tre ganger.",
            "Bekreft lokal programmering i Nimly Manager.",
            "Lås låsen, og lås deretter opp med den nye fingeren for verifisering.",
        )

    def confirm_local_programming(self, *, now: datetime) -> None:
        """Confirm that the physical programming sequence completed."""

        self._expire(now)
        if self.state is not EnrollmentState.LOCAL_PROGRAMMING:
            raise FingerprintEnrollmentError(
                f"kan ikke bekrefte lokal programmering fra {self.state}"
            )
        self.state = EnrollmentState.AWAITING_VERIFICATION

    def observe_unlock(
        self,
        *,
        source: str,
        user_slot: int,
        now: datetime,
    ) -> bool:
        """Verify only the expected fingerprint source and exact user slot."""

        self._expire(now)
        if self.state is not EnrollmentState.AWAITING_VERIFICATION:
            return False
        if source.strip().lower() not in FINGERPRINT_SOURCES:
            return False
        if user_slot != self.slot:
            return False
        self.state = EnrollmentState.VERIFIED
        self.verified_at = now
        return True

    def cancel(self, *, now: datetime) -> None:
        """Cancel an active session."""

        self._expire(now)
        if self.state in TERMINAL_STATES:
            raise FingerprintEnrollmentError(f"kan ikke avbryte fra {self.state}")
        self.state = EnrollmentState.CANCELLED

    def refresh(self, *, now: datetime) -> EnrollmentState:
        """Apply timeout and return the current state."""

        self._expire(now)
        return self.state

    def as_public_dict(self) -> dict[str, object]:
        """Return UI-safe metadata; no master or biometric data exists here."""

        return {
            "session_id": self.session_id,
            "person_id": self.person_id,
            "person_name": self.person_name,
            "slot": self.slot,
            "keypad_slot": self.keypad_slot,
            "state": self.state.value,
            "started_at": self.started_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "verified_at": (
                self.verified_at.isoformat() if self.verified_at is not None else None
            ),
        }

    def _expire(self, now: datetime) -> None:
        _require_timezone(now)
        if (
            self.state
            in {
                EnrollmentState.LOCAL_PROGRAMMING,
                EnrollmentState.AWAITING_VERIFICATION,
            }
            and now >= self.expires_at
        ):
            self.state = EnrollmentState.EXPIRED


def _require_timezone(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FingerprintEnrollmentError("now må ha tidssone")
