from nimly_ble_probe.firmware import FirmwareVersion, compatibility_for


def test_version_parser_is_numeric() -> None:
    assert FirmwareVersion.parse("4.7.90") == FirmwareVersion(4, 7, 90)
    assert FirmwareVersion.parse("4.7") is None
    assert FirmwareVersion.parse("v4.7.90") is None


def test_observed_firmware_is_below_documented_model_query_gate() -> None:
    result = compatibility_for("4.7.79")

    assert result == {
        "firmware_parsed": True,
        "ble_connection_documented": True,
        "device_model_query_documented": False,
        "fingerprint_enrollment": "unverified",
    }


def test_gate_accepts_minimum_version() -> None:
    assert compatibility_for("4.7.90")["device_model_query_documented"] is True


def test_unparseable_firmware_does_not_claim_support() -> None:
    result = compatibility_for("unknown")

    assert result["firmware_parsed"] is False
    assert result["ble_connection_documented"] == "unknown"
