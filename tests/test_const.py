import pytest

from custom_components.nimly_manager.const import state_topic


@pytest.mark.parametrize(
    ("device_name", "expected"),
    [
        ("doorlock_test", "zigbee2mqtt/doorlock_test"),
        ("zigbee2mqtt/doorlock_test", "zigbee2mqtt/doorlock_test"),
        ("/zigbee2mqtt/doorlock_test/", "zigbee2mqtt/doorlock_test"),
    ],
)
def test_state_topic_accepts_friendly_name_or_complete_topic(
    device_name: str,
    expected: str,
) -> None:
    assert state_topic("zigbee2mqtt", device_name) == expected
