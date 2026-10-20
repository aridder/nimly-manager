from nimly_ble_probe.advertisement import (
    inspect_advertisement,
    is_nimly_service_uuid,
    stable_private_id,
)
from nimly_ble_probe.constants import NIMLY_SERVICE_UUID


def test_recognizes_full_nimly_service_uuid() -> None:
    result = inspect_advertisement(
        address="AA:BB:CC:DD:EE:FF",
        name="Nimly",
        service_uuids=[NIMLY_SERVICE_UUID],
        service_data={},
        rssi=-55,
    )

    assert result is not None
    assert result.matched_by == ("service_uuid",)
    assert result.rssi == -55


def test_recognizes_fd00_service_data_in_short_and_full_forms() -> None:
    for uuid in ("FD00", "0xFD00", "0000fd00-0000-1000-8000-00805f9b34fb"):
        result = inspect_advertisement(
            address="device-1",
            name=None,
            service_uuids=[],
            service_data={uuid: bytes.fromhex("0102030405060708")},
        )
        assert result is not None
        assert result.service_data_kind == "seed_and_device_token"
        assert result.matched_by == ("service_data",)


def test_rejects_unrelated_advertisement() -> None:
    result = inspect_advertisement(
        address="device-2",
        name="Other",
        service_uuids=["180f"],
        service_data={},
    )

    assert result is None


def test_default_dictionary_redacts_identifiers() -> None:
    result = inspect_advertisement(
        address="AA:BB:CC:DD:EE:FF",
        name="Nimly",
        service_uuids=[],
        service_data={"fd00": bytes.fromhex("0102030405060708")},
    )
    assert result is not None

    public = result.as_dict()
    revealed = result.as_dict(reveal_identifiers=True)

    assert "address" not in public
    assert "service_data_hex" not in public
    assert revealed["address"] == "AA:BB:CC:DD:EE:FF"
    assert revealed["service_data_hex"] == "0102030405060708"


def test_private_id_is_stable_and_does_not_contain_address() -> None:
    first = stable_private_id("AA:BB:CC:DD:EE:FF")
    second = stable_private_id("AA:BB:CC:DD:EE:FF")

    assert first == second
    assert first.startswith("nimly-")
    assert "AA" not in first


def test_uuid_matching_is_case_insensitive() -> None:
    assert is_nimly_service_uuid(NIMLY_SERVICE_UUID.upper())


def test_observed_connect_module_service_data_is_classified_without_exposure() -> None:
    result = inspect_advertisement(
        address="device-3",
        name="Dør",
        service_uuids=[],
        service_data={"fd00": bytes(range(10))},
    )
    assert result is not None

    assert result.service_data_kind == "connect_module_seed_id_trailer"
    assert "service_data_hex" not in result.as_dict()


def test_zero_seed_eight_byte_data_reads_as_factory_fresh() -> None:
    result = inspect_advertisement(
        address="device-4",
        name=None,
        service_uuids=[],
        service_data={"fd00": bytes.fromhex("0000010203040506")},
    )
    assert result is not None
    assert result.enrollment_state == "factory"
    assert result.as_dict()["enrollment_state"] == "factory"


def test_nonzero_seed_eight_byte_data_reads_as_enrolled() -> None:
    result = inspect_advertisement(
        address="device-5",
        name=None,
        service_uuids=[],
        service_data={"fd00": bytes.fromhex("0102030405060708")},
    )
    assert result is not None
    assert result.enrollment_state == "enrolled"


def test_ten_byte_data_reads_seed_at_offset_zero_as_factory() -> None:
    # [seed 00 00][id 6B][trailer 2B]: the vendor app reads the seed first,
    # so a 10-byte payload with a zero seed is factory-fresh, not ambiguous.
    result = inspect_advertisement(
        address="device-6",
        name="Nimly",
        service_uuids=[],
        service_data={"fd00": bytes.fromhex("00000102030405060708")},
    )
    assert result is not None
    assert result.enrollment_state == "factory"
    assert result.service_data_kind == "connect_module_seed_id_trailer"


def test_ten_byte_data_with_nonzero_seed_reads_as_enrolled() -> None:
    result = inspect_advertisement(
        address="device-7",
        name="Nimly",
        service_uuids=[],
        service_data={"fd00": bytes(range(1, 11))},
    )
    assert result is not None
    assert result.enrollment_state == "enrolled"


def test_identifier_matches_reversed_mac_address() -> None:
    # The 2026-10-20 capture: id f0 8c 38 7c e9 c0 == reversed C0:E9:7C:38:8C:F0.
    result = inspect_advertisement(
        address="C0:E9:7C:38:8C:F0",
        name="Nimly",
        service_uuids=[],
        service_data={"fd00": bytes.fromhex("0000f08c387ce9c00000")},
    )
    assert result is not None
    assert result.enrollment_state == "factory"
    assert result.identifier_matches_address is True
    assert result.as_dict()["identifier_matches_address"] is True


def test_identifier_match_is_none_for_non_mac_address() -> None:
    result = inspect_advertisement(
        address="device-9",  # macOS CoreBluetooth UUID, not a MAC
        name="Nimly",
        service_uuids=[],
        service_data={"fd00": bytes.fromhex("0000f08c387ce9c00000")},
    )
    assert result is not None
    assert result.identifier_matches_address is None


def test_absent_service_data_has_unknown_enrollment_state() -> None:
    result = inspect_advertisement(
        address="device-8",
        name="Nimly",
        service_uuids=[NIMLY_SERVICE_UUID],
        service_data={},
    )
    assert result is not None
    assert result.enrollment_state == "unknown"
