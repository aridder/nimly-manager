"""Credential-free fingerprint slot registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .fingerprint_enrollment import FINGERPRINT_SLOT_MAX, FINGERPRINT_SLOT_MIN


class SlotStatus(StrEnum):
    """Evidence level for one fingerprint slot."""

    OBSERVED = "observed"
    VERIFIED = "verified"


@dataclass(slots=True)
class FingerprintSlot:
    """Safe metadata for a slot; never stores biometric material."""

    slot: int
    status: SlotStatus
    first_seen_at: str
    last_seen_at: str
    person_id: str | None = None
    person_name: str | None = None
    verified_at: str | None = None
    ble_slot: int | None = None

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return {
            "slot": self.slot,
            "keypad_slot": f"{self.slot:03d}",
            "status": self.status.value,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "person_id": self.person_id,
            "person_name": self.person_name,
            "verified_at": self.verified_at,
            "ble_slot": self.ble_slot,
        }


class FingerprintSlotRegistry:
    """Track only slots proven by an event or a verified enrollment."""

    def __init__(
        self,
        records: Mapping[int, FingerprintSlot] | None = None,
        *,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._records = dict(records or {})
        self._on_change = on_change

    @classmethod
    def from_storage(
        cls,
        data: object,
        *,
        on_change: Callable[[], None] | None = None,
    ) -> FingerprintSlotRegistry:
        """Restore valid records and ignore malformed storage data."""

        records: dict[int, FingerprintSlot] = {}
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
            return cls(on_change=on_change)
        for raw in data:
            if not isinstance(raw, Mapping):
                continue
            try:
                slot = int(raw["slot"])
                status = SlotStatus(str(raw["status"]))
                first_seen_at = str(raw["first_seen_at"])
                last_seen_at = str(raw["last_seen_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if not FINGERPRINT_SLOT_MIN <= slot <= FINGERPRINT_SLOT_MAX:
                continue
            records[slot] = FingerprintSlot(
                slot=slot,
                status=status,
                first_seen_at=first_seen_at,
                last_seen_at=last_seen_at,
                person_id=_optional_text(raw.get("person_id")),
                person_name=_optional_text(raw.get("person_name")),
                verified_at=_optional_text(raw.get("verified_at")),
                ble_slot=_optional_ble_slot(raw.get("ble_slot")),
            )
        return cls(records, on_change=on_change)

    def get(self, slot: int) -> FingerprintSlot | None:
        """Return a known slot."""

        return self._records.get(slot)

    def is_occupied(self, slot: int) -> bool:
        """Return true only when fingerprint use has provided evidence."""

        return slot in self._records

    def observe(self, *, slot: int, now: datetime) -> FingerprintSlot:
        """Record a fingerprint unlock from a slot without inventing an owner."""

        _validate_slot(slot)
        timestamp = _timestamp(now)
        record = self._records.get(slot)
        if record is None:
            record = FingerprintSlot(
                slot=slot,
                status=SlotStatus.OBSERVED,
                first_seen_at=timestamp,
                last_seen_at=timestamp,
            )
            self._records[slot] = record
        else:
            record.last_seen_at = timestamp
        self._changed()
        return record

    def verify(
        self,
        *,
        slot: int,
        person_id: str,
        person_name: str,
        now: datetime,
        ble_slot: int | None = None,
    ) -> FingerprintSlot:
        """Promote a slot after an exact enrollment verification event.

        ``ble_slot`` records which BLE slot a scan used, when the enrollment
        was started over BLE. It is kept as an observed data point only; no
        code derives a Zigbee slot from it.
        """

        record = self.observe(slot=slot, now=now)
        timestamp = _timestamp(now)
        record.status = SlotStatus.VERIFIED
        record.person_id = person_id.strip()
        record.person_name = person_name.strip()
        record.verified_at = timestamp
        record.last_seen_at = timestamp
        if ble_slot is not None:
            record.ble_slot = ble_slot
        self._changed()
        return record

    def used_ble_slots(self) -> list[int]:
        """BLE slots already paired with a Zigbee slot, for the slot picker."""

        return sorted(
            record.ble_slot
            for record in self._records.values()
            if record.ble_slot is not None
        )

    def as_list(self) -> list[dict[str, object]]:
        """Return records sorted by slot."""

        return [self._records[slot].as_dict() for slot in sorted(self._records)]

    def diagnostics(self) -> dict[str, int]:
        """Return counts without person names or other identifying metadata."""

        return {
            "observed": sum(
                record.status is SlotStatus.OBSERVED
                for record in self._records.values()
            ),
            "verified": sum(
                record.status is SlotStatus.VERIFIED
                for record in self._records.values()
            ),
        }

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()


def _validate_slot(slot: int) -> None:
    if not FINGERPRINT_SLOT_MIN <= slot <= FINGERPRINT_SLOT_MAX:
        raise ValueError(
            f"fingerprint-slot må være {FINGERPRINT_SLOT_MIN:03d}–"
            f"{FINGERPRINT_SLOT_MAX:03d}"
        )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("tidspunkt må ha tidssone")
    return value.isoformat()


def _optional_ble_slot(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 999 else None


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
