"""BLE-started scan: state machine, runtime coupling and library flow."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_nimly_ble import FW, FakeLock

from custom_components.nimly_manager.fingerprint_enrollment import (
    EnrollmentState,
    FingerprintEnrollmentError,
)
from custom_components.nimly_manager.fingerprint_scan import (
    BleFingerprintScan,
    ScanState,
)
from custom_components.nimly_manager.nimly_ble import enrollment, protocol
from custom_components.nimly_manager.nimly_ble.keystore import (
    KeyStoreError,
    OwnerRecord,
    owner_record_from_json,
)
from custom_components.nimly_manager.nimly_ble.protocol import CommandId
from custom_components.nimly_manager.nimly_ble.session import Session
from custom_components.nimly_manager.runtime import NimlyLockRuntime

NOW = datetime(2026, 10, 20, 20, 0, tzinfo=UTC)
KEY_HEX = "a1" * 16
DEVICE_HEX = "b2" * 6


def owner_record() -> OwnerRecord:
    return OwnerRecord(
        lock_address="AA:BB:CC:DD:EE:FF",
        device_id_hex=DEVICE_HEX,
        owner_key_hex=KEY_HEX,
        stage="enrolled",
        server_private_pem="-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
        name="Dor",
    )


# ---------------------------------------------------------- state machine


def test_scan_starts_connecting_and_only_ok_arms_verification() -> None:
    scan = BleFingerprintScan.start(
        person_id="p", person_name="Asbjørn", ble_slot=160, now=NOW
    )
    assert scan.state is ScanState.CONNECTING and scan.is_active
    assert not scan.armed_for_verification

    scan.mark_scanning(now=NOW + timedelta(seconds=3))
    assert scan.state is ScanState.SCANNING
    assert scan.finger_prompt_at == NOW + timedelta(seconds=3)

    scan.mark_scanned(
        now=NOW + timedelta(seconds=12),
        scan_status="ok",
        reported_slot=160,
        response_seconds=8.5,
        model="NimlyPro (23)",
        firmware="4.8.3",
    )
    assert scan.state is ScanState.AWAITING_VERIFICATION
    assert scan.armed_for_verification


def test_scan_error_answer_fails_and_never_arms() -> None:
    scan = BleFingerprintScan.start(
        person_id="p", person_name="Asbjørn", ble_slot=160, now=NOW
    )
    scan.mark_scanning(now=NOW)
    scan.mark_scanned(
        now=NOW, scan_status="error", reported_slot=160, response_seconds=0.4
    )
    assert scan.state is ScanState.FAILED
    assert not scan.armed_for_verification
    assert scan.error == "låsen svarte error"
    with pytest.raises(FingerprintEnrollmentError):
        scan.cancel(now=NOW)


def test_cancel_and_expiry_disarm() -> None:
    scan = BleFingerprintScan.start(
        person_id="p", person_name="Asbjørn", ble_slot=160, now=NOW
    )
    scan.mark_scanning(now=NOW)
    scan.cancel(now=NOW)
    assert scan.state is ScanState.CANCELLED
    scan.fail(now=NOW, error="late")  # terminal state stays
    assert scan.state is ScanState.CANCELLED

    expired = BleFingerprintScan.start(
        person_id="p", person_name="Asbjørn", ble_slot=160, now=NOW
    )
    assert expired.refresh(now=NOW + timedelta(minutes=15)) is ScanState.EXPIRED
    assert not expired.armed_for_verification


@pytest.mark.parametrize("slot", [149, 200, 11, 3])
def test_scan_rejects_slots_outside_ble_range(slot: int) -> None:
    with pytest.raises(FingerprintEnrollmentError):
        BleFingerprintScan.start(person_id="p", person_name="A", ble_slot=slot, now=NOW)


def test_public_dict_has_no_secret_fields() -> None:
    scan = BleFingerprintScan.start(
        person_id="p", person_name="Asbjørn", ble_slot=160, now=NOW
    )
    public = scan.as_public_dict()
    assert public["state"] == "connecting" and public["ble_slot"] == 160
    assert json.dumps(public)  # serializable for the websocket


# ------------------------------------------------------- runtime coupling


def armed_runtime(ble_slot: int = 160) -> tuple[NimlyLockRuntime, BleFingerprintScan]:
    runtime = NimlyLockRuntime(topic="zigbee2mqtt/Dør")
    scan = runtime.start_fingerprint_scan(
        person_id="person-asbjorn", person_name="Asbjørn", ble_slot=ble_slot, now=NOW
    )
    scan.mark_scanning(now=NOW + timedelta(seconds=2))
    scan.mark_scanned(
        now=NOW + timedelta(seconds=11),
        scan_status="ok",
        reported_slot=ble_slot,
        response_seconds=8.5,
    )
    return runtime, scan


def test_first_unknown_fingerprint_unlock_verifies_through_enrollment_flow() -> None:
    runtime, scan = armed_runtime()
    runtime.observe_mqtt_state({"state": "LOCK"}, now=NOW + timedelta(seconds=20))

    verification = runtime.observe_mqtt_state(
        {
            "state": "UNLOCK",
            "last_unlock_source": "fingerprintsensor",
            "last_unlock_user": 12,
        },
        now=NOW + timedelta(seconds=30),
    )

    assert verification is not None
    assert verification.user_slot == 12 and verification.ble_slot == 160
    assert scan.state is ScanState.VERIFIED and scan.zigbee_slot == 12
    # The unchanged enrollment object did the verification.
    assert runtime.enrollment is not None
    assert runtime.enrollment.state is EnrollmentState.VERIFIED
    assert runtime.enrollment.slot == 12
    assert scan.enrollment_session_id == runtime.enrollment.session_id
    record = runtime.slots.get(12)
    assert record is not None and record.person_name == "Asbjørn"
    assert record.ble_slot == 160
    assert runtime.slots.used_ble_slots() == [160]
    event = verification.as_event_data()
    assert event["ble_slot"] == 160 and event["user_id"] == 12


def test_known_slot_or_non_fingerprint_unlock_is_not_claimed() -> None:
    runtime, scan = armed_runtime()
    runtime.slots.observe(slot=11, now=NOW)  # a finger the registry already saw
    runtime.observe_mqtt_state({"state": "LOCK"}, now=NOW + timedelta(seconds=20))

    assert (
        runtime.observe_mqtt_state(
            {
                "state": "UNLOCK",
                "last_unlock_source": "fingerprintsensor",
                "last_unlock_user": 11,
            },
            now=NOW + timedelta(seconds=30),
        )
        is None
    )
    assert scan.state is ScanState.AWAITING_VERIFICATION

    runtime.observe_mqtt_state({"state": "LOCK"}, now=NOW + timedelta(seconds=40))
    assert (
        runtime.observe_mqtt_state(
            {"state": "UNLOCK", "last_unlock_source": "keypad", "last_unlock_user": 12},
            now=NOW + timedelta(seconds=50),
        )
        is None
    )
    assert scan.state is ScanState.AWAITING_VERIFICATION
    assert runtime.slots.get(12) is None


def test_retained_unlock_without_locked_transition_is_not_claimed() -> None:
    runtime, scan = armed_runtime()
    assert (
        runtime.observe_mqtt_state(
            {
                "state": "UNLOCK",
                "last_unlock_source": "fingerprintsensor",
                "last_unlock_user": 12,
            },
            now=NOW + timedelta(seconds=30),
        )
        is None
    )
    assert scan.state is ScanState.AWAITING_VERIFICATION


def test_cancelled_or_failed_scan_never_claims_a_later_unlock() -> None:
    runtime, scan = armed_runtime()
    runtime.cancel_fingerprint_scan(session_id=scan.session_id, now=NOW)
    runtime.observe_mqtt_state({"state": "LOCK"}, now=NOW + timedelta(seconds=20))

    assert (
        runtime.observe_mqtt_state(
            {
                "state": "UNLOCK",
                "last_unlock_source": "fingerprintsensor",
                "last_unlock_user": 12,
            },
            now=NOW + timedelta(seconds=30),
        )
        is None
    )
    assert runtime.enrollment is None
    assert (
        runtime.slots.get(12) is not None and runtime.slots.get(12).status == "observed"
    )


def test_one_workflow_per_lock_and_no_reuse_of_a_paired_ble_slot() -> None:
    runtime = NimlyLockRuntime(topic="zigbee2mqtt/Dør")
    runtime.start_enrollment(person_id="p", person_name="A", slot=42, now=NOW)
    with pytest.raises(FingerprintEnrollmentError):
        runtime.start_fingerprint_scan(
            person_id="p", person_name="B", ble_slot=160, now=NOW
        )

    runtime, _scan = armed_runtime()
    with pytest.raises(FingerprintEnrollmentError):
        runtime.start_enrollment(person_id="p", person_name="B", slot=42, now=NOW)
    with pytest.raises(FingerprintEnrollmentError):
        runtime.cancel_fingerprint_scan(session_id="nope", now=NOW)

    runtime.observe_mqtt_state({"state": "LOCK"}, now=NOW + timedelta(seconds=20))
    runtime.observe_mqtt_state(
        {
            "state": "UNLOCK",
            "last_unlock_source": "fingerprintsensor",
            "last_unlock_user": 12,
        },
        now=NOW + timedelta(seconds=30),
    )
    with pytest.raises(FingerprintEnrollmentError, match="allerede brukt"):
        runtime.start_fingerprint_scan(
            person_id="p", person_name="C", ble_slot=160, now=NOW + timedelta(minutes=1)
        )
    state = runtime.public_state(now=NOW + timedelta(minutes=1))
    assert state["used_ble_slots"] == [160]
    assert state["scan"]["state"] == "verified"


def test_zigbee_master_slot_is_never_claimed() -> None:
    runtime, scan = armed_runtime()
    runtime.observe_mqtt_state({"state": "LOCK"}, now=NOW + timedelta(seconds=20))
    assert (
        runtime.observe_mqtt_state(
            {
                "state": "UNLOCK",
                "last_unlock_source": "fingerprintsensor",
                "last_unlock_user": 0,
            },
            now=NOW + timedelta(seconds=30),
        )
        is None
    )
    assert scan.state is ScanState.AWAITING_VERIFICATION


# ------------------------------------------------------------ library flow


async def test_scan_fingerprint_prompts_before_the_write_and_reports_ok() -> None:
    lock = FakeLock()
    record = owner_record()
    lock.owner_key = record.owner_key
    lock.device_id = record.device_id
    session = Session(lock, firmware=FW, command_delay=0, timeout=2)
    prompts: list[list[CommandId]] = []

    result = await enrollment.scan_fingerprint(
        session,
        record,
        slot=160,
        firmware=FW,
        on_finger_prompt=lambda: prompts.append(list(lock.seen)),
    )

    assert result["scan_status"] == "ok" and result["reported_slot"] == 160
    assert result["model"] == "NimlyPro (23)" and result["firmware"] == "4.8.3"
    assert lock.scanned_slots == [160]
    # The prompt fired after auth and before FingerprintScan reached the lock.
    assert prompts and CommandId.FINGERPRINT_SCAN not in prompts[0]
    assert CommandId.USER_AUTH_FINALIZE in prompts[0]
    assert lock.auth_begin_device_id == record.device_id


async def test_scan_fingerprint_refuses_unknown_model_before_authenticating() -> None:
    lock = FakeLock(model=99)
    session = Session(lock, firmware=FW, command_delay=0, timeout=2)
    with pytest.raises(enrollment.EnrollmentRefused, match="modell"):
        await enrollment.scan_fingerprint(
            session, owner_record(), slot=160, firmware=FW
        )
    assert CommandId.USER_AUTH_BEGIN not in lock.seen
    assert lock.scanned_slots == []


async def test_scan_fingerprint_refuses_old_firmware_and_unenrolled_record() -> None:
    lock = FakeLock()
    session = Session(lock, firmware=(4, 7, 79), command_delay=0, timeout=2)
    with pytest.raises(enrollment.EnrollmentRefused, match="firmware"):
        await enrollment.scan_fingerprint(
            session, owner_record(), slot=160, firmware=(4, 7, 79)
        )
    half = owner_record()
    half.stage = "owner_key_received"
    with pytest.raises(enrollment.EnrollmentRefused):
        await enrollment.scan_fingerprint(session, half, slot=160, firmware=FW)
    assert lock.seen == []


async def test_scan_fingerprint_rejects_zigbee_range_slots() -> None:
    lock = FakeLock()
    session = Session(lock, firmware=FW, command_delay=0, timeout=2)
    with pytest.raises(protocol.ProtocolError):
        await enrollment.scan_fingerprint(session, owner_record(), slot=11, firmware=FW)
    assert lock.seen == []


# ------------------------------------------------------------- owner record


def test_owner_record_repr_and_public_dict_hide_the_key() -> None:
    record = owner_record()
    assert KEY_HEX not in repr(record) and "PRIVATE KEY" not in repr(record)
    assert KEY_HEX not in str(record)
    public = record.public_dict()
    assert KEY_HEX not in json.dumps(public) and "PRIVATE" not in json.dumps(public)
    assert set(record.as_dict()) >= {"owner_key_hex", "server_private_pem"}


def test_owner_record_from_json_round_trips_and_validates() -> None:
    record = owner_record()
    parsed = owner_record_from_json(json.dumps(record.as_dict()))
    assert parsed.owner_key == record.owner_key
    assert parsed.device_id == record.device_id

    for bad in (
        "not json",
        "[]",
        json.dumps({**record.as_dict(), "stage": "owner_key_received"}),
        json.dumps({**record.as_dict(), "owner_key_hex": "zz" * 16}),
        json.dumps({**record.as_dict(), "owner_key_hex": "a1" * 15}),
        json.dumps({**record.as_dict(), "device_id_hex": "b2" * 5}),
        json.dumps({"at": 1, "report": {}}),  # the preflight file
    ):
        with pytest.raises(KeyStoreError):
            owner_record_from_json(bad)
