"""Owner flows against a lock: preflight, one-time enrollment, fingerprint scan.

Each flow is a plain coroutine over a ``Session`` and an ``OwnerKeyStore`` so
it can run from a laptop today and from Home Assistant later. ``enroll`` is
the only irreversible one and is gated behind a recent, passing ``preflight``.
"""

from __future__ import annotations

import asyncio
import secrets
import time

from cryptography.hazmat.primitives import serialization

from . import crypto, protocol
from .keystore import KeyStoreError, OwnerKeyStore, OwnerRecord
from .protocol import CommandId
from .session import Session

MODEL_QUERY_FIRMWARE = (4, 7, 90)


class EnrollmentRefused(RuntimeError):
    """A precondition for an irreversible step did not hold."""


async def preflight(
    session: Session, *, lock_address: str, firmware: tuple[int, int, int]
) -> dict[str, object]:
    """Prove crypto, framing and the default owner credential; change nothing."""

    report: dict[str, object] = {
        "lock_address": lock_address,
        "firmware": ".".join(map(str, firmware)),
        "link_handshake": False,
        "model": None,
        "fingerprint_capable": None,
        "default_owner_auth": False,
    }
    await session.handshake()
    report["link_handshake"] = True
    if firmware >= MODEL_QUERY_FIRMWARE:
        model = await session.send(CommandId.DEVICE_MODEL_GET)
        model_id, name, fingerprint = protocol.parse_model(model.payload)
        report["model"] = f"{name} ({model_id})"
        report["fingerprint_capable"] = fingerprint
    await session.owner_authenticate(
        crypto.DEFAULT_OWNER_KEY,
        user_id=crypto.DEFAULT_ADMIN_USER_ID,
        device_id=crypto.DEFAULT_DEVICE_ID,
    )
    report["default_owner_auth"] = True
    return report


async def enroll(
    session: Session,
    store: OwnerKeyStore,
    *,
    lock_address: str,
    name: str,
    now: float | None = None,
) -> OwnerRecord:
    """Take local ownership. Persists the new key before any further write."""

    if store.exists(lock_address):
        raise EnrollmentRefused(
            f"an owner record already exists at {store.path_for(lock_address)}"
        )
    if not store.preflight_passed_recently(lock_address):
        raise EnrollmentRefused("run preflight first (valid for 30 minutes)")

    await session.handshake()
    await session.owner_authenticate(
        crypto.DEFAULT_OWNER_KEY,
        user_id=crypto.DEFAULT_ADMIN_USER_ID,
        device_id=crypto.DEFAULT_DEVICE_ID,
    )

    device_id = secrets.token_bytes(6)
    server_private = crypto.generate_key_pair()
    server_pem = server_private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")

    owner_key = await session.owner_update(user_id=0, credentials=0)
    # Point of no return: the default key presumably no longer opens the lock.
    record = OwnerRecord(
        lock_address=lock_address,
        device_id_hex=device_id.hex(),
        owner_key_hex=owner_key.hex(),
        stage="owner_key_received",
        server_private_pem=server_pem,
        name=name,
    )
    store.save(record)

    await session.send(CommandId.DEVICE_ID_SET, protocol.device_id_payload(device_id))
    await session.send(
        CommandId.CURRENT_TIME_SET,
        protocol.current_time_payload(time.time() if now is None else now),
    )
    await session.send(
        CommandId.SERVER_KEY_UPDATE,
        protocol.server_key_payload(
            crypto.public_key_to_wire(server_private.public_key())
        ),
    )
    await session.send(CommandId.DEVICE_NAME_SET, protocol.device_name_payload(name))

    record.stage = "enrolled"
    store.save(record)
    return record


async def fingerprint_scan(
    session: Session,
    store: OwnerKeyStore,
    *,
    lock_address: str,
    slot: int,
    event_wait: float = 30.0,
) -> dict[str, object]:
    """Ask the lock to enrol a finger into one BLE slot (150–199)."""

    record = store.load(lock_address)
    if record is None or record.stage != "enrolled":
        raise KeyStoreError("no enrolled owner record for this lock")
    payload = protocol.fingerprint_slot_payload(slot)

    await session.handshake()
    await session.owner_authenticate(
        record.owner_key, user_id=0, device_id=record.device_id
    )
    sent_at = time.monotonic()
    response = await session.send(CommandId.FINGERPRINT_SCAN, payload)
    response_seconds = round(time.monotonic() - sent_at, 1)
    reported_slot, lock_status = protocol.parse_fingerprint_scan(response.payload)
    status_name = {
        0: "ok", 1: "error", 2: "unknown_command", 3: "crc_error",
        4: "invalid_data", 5: "no_space_left", 6: "no_match",
    }.get(lock_status, f"unknown_{lock_status}")

    # The finger goes on now; the lock reports UserAdded as an event.
    deadline = time.monotonic() + event_wait
    events: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        events = [e for e in session.events if e.get("event") == "user_added"]
        if events:
            break
        await asyncio.sleep(0.5)

    return {
        "requested_slot": slot,
        "reported_slot": reported_slot,
        "scan_status": status_name,
        "response_seconds": response_seconds,
        "user_added_events": events,
    }
