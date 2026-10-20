"""Recognition and privacy-safe formatting of Nimly BLE advertisements."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256

from .constants import (
    NIMLY_ADVERTISING_UUID,
    NIMLY_ADVERTISING_UUID_16,
    NIMLY_SERVICE_UUID,
)


def normalize_uuid(value: str) -> str:
    """Normalize UUID spellings used by different Bleak backends."""

    return value.strip().lower().replace("0x", "")


def is_nimly_service_uuid(value: str) -> bool:
    normalized = normalize_uuid(value)
    return normalized in {
        NIMLY_SERVICE_UUID,
        NIMLY_ADVERTISING_UUID,
        NIMLY_ADVERTISING_UUID_16,
    }


def stable_private_id(value: str) -> str:
    """Return a stable local selector without printing a BLE address."""

    digest = sha256(value.encode("utf-8", errors="replace")).hexdigest()
    return f"nimly-{digest[:12]}"


@dataclass(frozen=True, slots=True)
class NimlyAdvertisement:
    """Sanitized view of one Nimly advertisement."""

    probe_id: str
    name: str | None
    address: str
    rssi: int | None
    service_data: bytes | None
    matched_by: tuple[str, ...]

    @property
    def service_data_kind(self) -> str:
        if self.service_data is None:
            return "not_present"
        if len(self.service_data) == 10:
            # Connect Module observed in the field: [seed 2][id 6][trailer 2].
            # The 6-byte id is the lock's own BLE address, byte-reversed on the
            # air; the trailing two bytes were 00 00 in the capture.
            return "connect_module_seed_id_trailer"
        if len(self.service_data) == 8:
            # The layout the vendor app parses: [seed 2][id 6].
            return "seed_and_device_token"
        return "unknown"

    @property
    def _seed(self) -> bytes | None:
        """The first two service-data bytes, which the vendor app reads as seed.

        The vendor's own ``BleScanner`` takes the first 8 bytes as
        ``[seed: 2B][identifier: 6B]`` and ignores anything past them, and it
        recognises an *enrolled* lock by comparing those 6 id bytes to
        ``SHA-1(seed || deviceId)[0:6]``. Of the three ways a 10-byte payload
        could be laid out, only ``[seed][id][trailer]`` lets that comparison
        succeed on an enrolled lock — the other two would make the app read a
        wrong id and never find its own locks, which it demonstrably does.
        So the seed is always the first two bytes, at any length we accept.
        The 2026-10-20 capture settled it: id == reversed advertising address,
        confirming seed-first with a trailing pad. See
        ``docs/fingerprint-enrollment.md``.
        """

        data = self.service_data
        if data is None or len(data) not in (8, 10):
            return None
        return data[0:2]

    @property
    def enrollment_state(self) -> str:
        """Factory-fresh vs enrolled BLE state, from the seed.

        Seed ``00 00`` means a lock never enrolled over BLE (the default owner
        key still opens it, and local owner enrollment needs no factory reset);
        any other seed means an enrolled lock. An unrecognised length, or no
        service data, is ``unknown`` — never a guess. See ``_seed`` for why the
        seed is trusted at offset 0 even for the 10-byte payload.
        """

        seed = self._seed
        if seed is None:
            return "unknown"
        return "factory" if seed == b"\x00\x00" else "enrolled"

    @property
    def identifier_matches_address(self) -> bool | None:
        """Whether the 6-byte identifier is this lock's reversed BLE address.

        True/False when both the identifier and a MAC-shaped address are
        available, else None (e.g. a macOS CoreBluetooth UUID, which is not a
        MAC). A match corroborates the seed-first layout and the factory
        reading in one stroke; a miss does not flip the verdict.
        """

        data = self.service_data
        if data is None or len(data) not in (8, 10):
            return None
        identifier = data[2:8]
        hex_only = self.address.replace(":", "").replace("-", "")
        try:
            address_bytes = bytes.fromhex(hex_only)
        except ValueError:
            return None
        if len(address_bytes) != 6:
            return None
        return identifier[::-1] == address_bytes

    def as_dict(self, *, reveal_identifiers: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "probe_id": self.probe_id,
            "name": self.name,
            "rssi": self.rssi,
            "matched_by": list(self.matched_by),
            "service_data_kind": self.service_data_kind,
            "enrollment_state": self.enrollment_state,
            "identifier_matches_address": self.identifier_matches_address,
            "service_data_length": (
                len(self.service_data) if self.service_data is not None else None
            ),
        }
        if reveal_identifiers:
            result["address"] = self.address
            result["service_data_hex"] = (
                self.service_data.hex() if self.service_data is not None else None
            )
        return result


def inspect_advertisement(
    *,
    address: str,
    name: str | None,
    service_uuids: Sequence[str] | None,
    service_data: Mapping[str, bytes] | None,
    rssi: int | None = None,
) -> NimlyAdvertisement | None:
    """Return a sanitized candidate when an advertisement looks like Nimly."""

    matches: list[str] = []
    nimly_data: bytes | None = None

    for service_uuid in service_uuids or ():
        if is_nimly_service_uuid(service_uuid):
            matches.append("service_uuid")

    for service_uuid, value in (service_data or {}).items():
        if is_nimly_service_uuid(service_uuid):
            matches.append("service_data")
            nimly_data = bytes(value)
            break

    if not matches:
        return None

    return NimlyAdvertisement(
        probe_id=stable_private_id(address),
        name=name,
        address=address,
        rssi=rssi,
        service_data=nimly_data,
        matched_by=tuple(dict.fromkeys(matches)),
    )
