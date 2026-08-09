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

    def as_dict(self, *, reveal_identifiers: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "probe_id": self.probe_id,
            "name": self.name,
            "rssi": self.rssi,
            "matched_by": list(self.matched_by),
            "service_data_kind": self.service_data_kind,
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
