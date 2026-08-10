from datetime import UTC, datetime, timedelta

import pytest

from custom_components.nimly_manager.slots import (
    FingerprintSlotRegistry,
    SlotStatus,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def test_observed_slot_has_no_invented_owner() -> None:
    registry = FingerprintSlotRegistry()

    slot = registry.observe(slot=17, now=NOW)

    assert slot.status is SlotStatus.OBSERVED
    assert slot.person_id is None
    assert slot.person_name is None
    assert registry.is_occupied(17)


def test_verified_slot_round_trips_through_safe_storage() -> None:
    registry = FingerprintSlotRegistry()
    registry.verify(
        slot=42,
        person_id="person-asbjorn",
        person_name="Asbjørn",
        now=NOW,
    )

    restored = FingerprintSlotRegistry.from_storage(registry.as_list())
    slot = restored.get(42)

    assert slot is not None
    assert slot.status is SlotStatus.VERIFIED
    assert slot.person_name == "Asbjørn"
    assert slot.verified_at == NOW.isoformat()


def test_later_observation_preserves_verified_owner() -> None:
    registry = FingerprintSlotRegistry()
    registry.verify(
        slot=42,
        person_id="person-asbjorn",
        person_name="Asbjørn",
        now=NOW,
    )

    registry.observe(slot=42, now=NOW + timedelta(minutes=1))
    slot = registry.get(42)

    assert slot is not None
    assert slot.status is SlotStatus.VERIFIED
    assert slot.person_name == "Asbjørn"
    assert slot.last_seen_at == (NOW + timedelta(minutes=1)).isoformat()


def test_restore_ignores_malformed_and_out_of_range_records() -> None:
    registry = FingerprintSlotRegistry.from_storage(
        [
            {
                "slot": 2,
                "status": "observed",
                "first_seen_at": "x",
                "last_seen_at": "x",
            },
            {
                "slot": 200,
                "status": "verified",
                "first_seen_at": "x",
                "last_seen_at": "x",
            },
            {
                "slot": 3,
                "status": "unsupported",
                "first_seen_at": "x",
                "last_seen_at": "x",
            },
            {"not": "a slot"},
        ]
    )

    assert registry.as_list() == []


@pytest.mark.parametrize("slot", [2, 200])
def test_observation_rejects_slot_outside_nimly_range(slot: int) -> None:
    with pytest.raises(ValueError, match="003–199"):
        FingerprintSlotRegistry().observe(slot=slot, now=NOW)
