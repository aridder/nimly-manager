from datetime import UTC, datetime, timedelta

import pytest

from custom_components.nimly_manager.fingerprint_enrollment import (
    EnrollmentState,
    FingerprintEnrollment,
    FingerprintEnrollmentError,
)

NOW = datetime(2026, 8, 9, 20, 0, tzinfo=UTC)


def enrollment(slot: int = 3) -> FingerprintEnrollment:
    return FingerprintEnrollment.start(
        person_id="person-asbjorn",
        person_name="Asbjørn",
        slot=slot,
        now=NOW,
    )


@pytest.mark.parametrize("slot", [3, 199])
def test_accepts_documented_fingerprint_slot_boundaries(slot: int) -> None:
    session = enrollment(slot)

    assert session.keypad_slot == f"{slot:03d}"
    assert f"Tast {slot:03d}*." in session.instructions
    assert "Lås låsen" in session.instructions[-1]


@pytest.mark.parametrize("slot", [2, 200])
def test_rejects_slot_outside_documented_range(slot: int) -> None:
    with pytest.raises(FingerprintEnrollmentError, match="003–199"):
        enrollment(slot)


def test_requires_explicit_local_confirmation_before_event_verification() -> None:
    session = enrollment()

    assert not session.observe_unlock(
        source="fingerprintsensor", user_slot=3, now=NOW + timedelta(seconds=10)
    )
    assert session.state is EnrollmentState.LOCAL_PROGRAMMING


@pytest.mark.parametrize("source", ["fingerprintsensor", "fingerprint"])
def test_matching_fingerprint_unlock_verifies_session(source: str) -> None:
    session = enrollment(42)
    session.confirm_local_programming(now=NOW + timedelta(minutes=1))

    verified = session.observe_unlock(
        source=source,
        user_slot=42,
        now=NOW + timedelta(minutes=2),
    )

    assert verified
    assert session.state is EnrollmentState.VERIFIED
    assert session.verified_at == NOW + timedelta(minutes=2)


def test_wrong_source_or_slot_does_not_verify() -> None:
    session = enrollment(42)
    session.confirm_local_programming(now=NOW + timedelta(minutes=1))

    assert not session.observe_unlock(
        source="keypad", user_slot=42, now=NOW + timedelta(minutes=2)
    )
    assert not session.observe_unlock(
        source="fingerprintsensor", user_slot=43, now=NOW + timedelta(minutes=3)
    )
    assert session.state is EnrollmentState.AWAITING_VERIFICATION


def test_session_expires_and_cannot_verify_late_event() -> None:
    session = enrollment()
    session.confirm_local_programming(now=NOW + timedelta(minutes=1))

    assert not session.observe_unlock(
        source="fingerprintsensor", user_slot=3, now=NOW + timedelta(minutes=15)
    )
    assert session.state is EnrollmentState.EXPIRED


def test_public_metadata_contains_no_credential_material() -> None:
    public = enrollment().as_public_dict()

    assert set(public) == {
        "session_id",
        "person_id",
        "person_name",
        "slot",
        "keypad_slot",
        "state",
        "started_at",
        "expires_at",
        "verified_at",
    }


def test_cancel_is_terminal() -> None:
    session = enrollment()
    session.cancel(now=NOW + timedelta(minutes=1))

    assert session.state is EnrollmentState.CANCELLED
    with pytest.raises(FingerprintEnrollmentError):
        session.cancel(now=NOW + timedelta(minutes=2))
