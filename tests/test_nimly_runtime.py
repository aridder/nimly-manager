from datetime import UTC, datetime, timedelta

import pytest

from custom_components.nimly_manager.fingerprint_enrollment import (
    EnrollmentState,
    FingerprintEnrollmentError,
)
from custom_components.nimly_manager.runtime import NimlyLockRuntime

NOW = datetime(2026, 8, 9, 20, 0, tzinfo=UTC)


def awaiting_runtime(slot: int = 42) -> NimlyLockRuntime:
    runtime = NimlyLockRuntime(topic="zigbee2mqtt/Dør")
    session = runtime.start_enrollment(
        person_id="person-asbjorn",
        person_name="Asbjørn",
        slot=slot,
        now=NOW,
    )
    runtime.confirm_enrollment(
        session_id=session.session_id,
        now=NOW + timedelta(seconds=1),
    )
    return runtime


def test_retained_unlocked_state_does_not_verify() -> None:
    runtime = awaiting_runtime()

    result = runtime.observe_mqtt_state(
        {
            "state": "UNLOCK",
            "last_unlock_source": "fingerprintsensor",
            "last_unlock_user": "42",
        },
        now=NOW + timedelta(seconds=2),
    )

    assert result is None
    assert runtime.enrollment is not None
    assert runtime.enrollment.state is EnrollmentState.AWAITING_VERIFICATION


def test_locked_to_unlocked_matching_fingerprint_verifies() -> None:
    runtime = awaiting_runtime()
    runtime.observe_mqtt_state(
        {"state": "LOCK", "last_used_pin_code": "8472"},
        now=NOW + timedelta(seconds=2),
    )

    result = runtime.observe_mqtt_state(
        {
            "state": "UNLOCK",
            "last_unlock_source": "fingerprintsensor",
            "last_unlock_user": "42",
            "last_used_pin_code": "8472",
        },
        now=NOW + timedelta(seconds=3),
    )

    assert result is not None
    assert result.source == "fingerprintsensor"
    assert result.user_slot == 42
    assert "8472" not in repr(result.as_event_data())
    assert runtime.enrollment is not None
    assert runtime.enrollment.state is EnrollmentState.VERIFIED
    slot = runtime.slots.get(42)
    assert slot is not None
    assert slot.status == "verified"
    assert slot.person_name == "Asbjørn"


def test_repeated_unlocked_payload_does_not_verify() -> None:
    runtime = awaiting_runtime()
    payload = {
        "state": "UNLOCK",
        "last_unlock_source": "fingerprintsensor",
        "last_unlock_user": 42,
    }

    assert runtime.observe_mqtt_state(payload, now=NOW + timedelta(seconds=2)) is None
    assert runtime.observe_mqtt_state(payload, now=NOW + timedelta(seconds=3)) is None


@pytest.mark.parametrize(
    ("source", "slot"),
    [("keypad", 42), ("fingerprintsensor", 43), ("", 42), ("fingerprint", "x")],
)
def test_wrong_or_malformed_unlock_evidence_does_not_verify(
    source: str, slot: int | str
) -> None:
    runtime = awaiting_runtime()
    runtime.observe_mqtt_state({"lock_state": "LOCKED"}, now=NOW + timedelta(seconds=2))

    assert (
        runtime.observe_mqtt_state(
            {
                "lock_state": "UNLOCKED",
                "last_unlock_source": source,
                "last_unlock_user": slot,
            },
            now=NOW + timedelta(seconds=3),
        )
        is None
    )


def test_active_session_cannot_be_replaced() -> None:
    runtime = awaiting_runtime()

    with pytest.raises(FingerprintEnrollmentError, match="allerede en aktiv"):
        runtime.start_enrollment(
            person_id="person-madeleine",
            person_name="Madeleine",
            slot=43,
            now=NOW + timedelta(seconds=2),
        )


def test_confirmation_requires_exact_session_id() -> None:
    runtime = NimlyLockRuntime(topic="zigbee2mqtt/Dør")
    runtime.start_enrollment(
        person_id="person-asbjorn",
        person_name="Asbjørn",
        slot=42,
        now=NOW,
    )

    with pytest.raises(FingerprintEnrollmentError, match="ukjent eller utløpt"):
        runtime.confirm_enrollment(
            session_id="stale-session",
            now=NOW + timedelta(seconds=1),
        )


def test_diagnostics_never_retain_raw_payload_or_pin() -> None:
    runtime = awaiting_runtime()
    runtime.observe_mqtt_state(
        {"state": "LOCK", "last_used_pin_code": "8472", "battery": 88},
        now=NOW + timedelta(seconds=2),
    )

    diagnostics = runtime.diagnostics(now=NOW + timedelta(seconds=3))

    assert set(diagnostics) == {
        "state_topic",
        "lock_state",
        "last_mqtt_at",
        "fingerprint_enrollment",
        "fingerprint_slot_counts",
    }
    assert "8472" not in repr(diagnostics)
    assert "battery" not in repr(diagnostics)


def test_fingerprint_unlock_is_observed_without_active_enrollment() -> None:
    runtime = NimlyLockRuntime(topic="zigbee2mqtt/Dør")
    runtime.observe_mqtt_state({"state": "LOCK"}, now=NOW)

    result = runtime.observe_mqtt_state(
        {
            "state": "UNLOCK",
            "last_unlock_source": "fingerprintsensor",
            "last_unlock_user": 77,
        },
        now=NOW + timedelta(seconds=1),
    )

    assert result is None
    slot = runtime.slots.get(77)
    assert slot is not None
    assert slot.status == "observed"
    assert slot.person_name is None


def test_known_slot_cannot_be_selected_for_enrollment() -> None:
    runtime = NimlyLockRuntime(topic="zigbee2mqtt/Dør")
    runtime.slots.observe(slot=42, now=NOW)

    with pytest.raises(FingerprintEnrollmentError, match="bekreftet opptatt"):
        runtime.start_enrollment(
            person_id="person-asbjorn",
            person_name="Asbjørn",
            slot=42,
            now=NOW + timedelta(seconds=1),
        )
