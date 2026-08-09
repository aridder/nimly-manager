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

    assert result.service_data_kind == "connect_module_token_observed"
    assert "service_data_hex" not in result.as_dict()
