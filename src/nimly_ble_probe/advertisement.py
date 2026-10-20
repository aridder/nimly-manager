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
            # Observed physically from a Connect Module while the official
            # app's Add device flow was active. Keep the value opaque until
            # the two extra bytes have been verified by a packet capture.
            return "connect_module_token_observed"
        if len(self.service_data) == 8:
            # Reverse-engineering documents two 8-byte variants. Without a
            # known device id they cannot be distinguished safely.
            return "seed_and_device_token"
        return "unknown"

    @property
    def enrollment_state(self) -> str:
        """Report factory-fresh vs enrolled BLE state from the seed, honestly.

        The onesti-lock BLE protocol notes read the 0xFD00 service data as
        ``[seed: 2B][identifier: 6B]``: an all-zero seed means a lock that has
        never been enrolled over BLE (the default owner key still opens it),
        any other seed means an enrolled lock whose identifier is a SHA-1
        prefix. This read decides whether local owner enrollment needs a
        physical factory reset, so it must never guess.

        The only advertisement anyone has observed carried 10 bytes, not the
        documented 8, and the two extra bytes may sit before, inside or after
        the identifier. When the length is not exactly 8 we therefore evaluate
        both plausible seed offsets and refuse to decide if they disagree.
        """

        data = self.service_data
        if data is None:
            return "unknown"
        if len(data) == 8:
            return "factory" if data[0:2] == b"\x00\x00" else "enrolled"
        if len(data) == 10:
            # Try the seed at the two offsets a 10-byte layout allows.
            front_zero = data[0:2] == b"\x00\x00"
            shifted_zero = data[2:4] == b"\x00\x00"
            if front_zero == shifted_zero:
                return "factory" if front_zero else "enrolled"
            # One offset looks factory-fresh and the other does not; the
            # layout is undecided, so do not claim either state.
            return "ambiguous"
        return "unknown"

    def as_dict(self, *, reveal_identifiers: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "probe_id": self.probe_id,
            "name": self.name,
            "rssi": self.rssi,
            "matched_by": list(self.matched_by),
            "service_data_kind": self.service_data_kind,
            "enrollment_state": self.enrollment_state,
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
