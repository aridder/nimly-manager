"""Library tests with a fake lock speaking the documented protocol."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from pathlib import Path

import pytest

from nimly_ble import crypto, enrollment, protocol
from nimly_ble.keystore import OwnerKeyStore
from nimly_ble.protocol import Command, CommandId, PacketType, Response
from nimly_ble.session import CommandFailed, Session

FW = (4, 8, 3)


# ------------------------------------------------------------------ crypto

def test_wire_public_key_roundtrip_is_little_endian_per_coordinate() -> None:
    private = crypto.generate_key_pair()
    wire = crypto.public_key_to_wire(private.public_key())
    assert len(wire) == 64
    numbers = crypto.public_key_from_wire(wire).public_numbers()
    assert numbers == private.public_key().public_numbers()
    assert int.from_bytes(wire[:32], "little") == numbers.x


def test_both_sides_derive_the_same_reversed_secret() -> None:
    a, b = crypto.generate_key_pair(), crypto.generate_key_pair()
    sa = crypto.reversed_shared_secret(a, crypto.public_key_to_wire(b.public_key()))
    sb = crypto.reversed_shared_secret(b, crypto.public_key_to_wire(a.public_key()))
    assert sa == sb and len(sa) == 32


def test_cbc_zero_pads_and_is_one_run_per_message() -> None:
    key, iv = bytes(range(16)), bytes(range(16, 32))
    ct = crypto.encrypt(key, iv, b"abc")
    assert len(ct) == 16
    assert crypto.decrypt(key, iv, ct) == b"abc" + bytes(13)
    assert crypto.encrypt(key, iv, b"abc") == ct  # same message, same ciphertext
    assert crypto.encrypt(key, iv, b"") == b""
    with pytest.raises(ValueError):
        crypto.decrypt(key, iv, b"\x00" * 15)


def test_owner_auth_answer_is_encrypted_inverted_nonce() -> None:
    owner, iv, nonce = secrets.token_bytes(16), secrets.token_bytes(16), secrets.token_bytes(16)
    challenge = crypto.make_owner_challenge(owner, iv, nonce)
    answer = crypto.owner_auth_answer(owner, iv, challenge)
    assert crypto.decrypt(owner, iv, answer) == crypto.bit_invert(nonce)


# ---------------------------------------------------------------- framing

def test_short_payload_is_a_single_packet() -> None:
    frames = protocol.frame_payload(b"x" * 12, encrypted=False)
    assert len(frames) == 1 and frames[0][0] == PacketType.SINGLE


def test_handshake_sized_payload_frames_as_app_does_and_reassembles() -> None:
    payload = Command(CommandId.EXCHANGE_KEY_PUB_M, 1, bytes(64)).to_bytes()
    assert len(payload) == 68
    frames = protocol.frame_payload(payload, encrypted=False)
    # 12 in BlobStart, then 16+16+16 streamed, last 8 in BlobComplete.
    assert [f[0] for f in frames] == [3, 4, 4, 4, 5]
    assert [f[3] for f in frames] == [1, 2, 3, 4, 5]
    assert frames[0][4] == 0x00  # unencrypted flag
    reasm = protocol.Reassembler()
    out = [reasm.feed(f) for f in frames]
    assert out[:-1] == [None] * 4 and out[-1] == payload


def test_reassembler_rejects_sequence_gap_and_bad_total() -> None:
    frames = protocol.frame_payload(bytes(40), encrypted=True)
    reasm = protocol.Reassembler()
    reasm.feed(frames[0])
    with pytest.raises(protocol.ProtocolError):
        reasm.feed(frames[2])


def test_command_ref_counter_wraps_at_127_and_is_fixed_below_gate() -> None:
    counting = protocol.CommandRefCounter(counting=True)
    seq = [counting.next() for _ in range(128)]
    assert seq[0] == 1 and seq[126] == 127 and seq[127] == 1
    assert protocol.CommandRefCounter(counting=False).next() == 16


def test_payload_builders_and_ranges() -> None:
    assert protocol.device_name_payload("Dør".encode("ascii", "ignore").decode()) == b"Dr" + bytes(7)
    assert protocol.device_name_payload("abcdefghij") == b"abcdefgh\x00"
    assert protocol.current_time_payload(protocol.TIME_EPOCH_UNIX + 120) == (2).to_bytes(4, "little")
    with pytest.raises(protocol.ProtocolError):
        protocol.current_time_payload(protocol.TIME_EPOCH_UNIX - 60)
    assert protocol.fingerprint_slot_payload(150) == b"\x96\x00"
    for bad in (149, 200, 3):
        with pytest.raises(protocol.ProtocolError):
            protocol.fingerprint_slot_payload(bad)
    assert protocol.parse_model(b"\x17") == (23, "NimlyPro", True)
    assert protocol.parse_model(b"\x63") == (99, "Unknown", False)


# -------------------------------------------------------------- fake lock

class FakeLock:
    """Transport whose far end behaves like a factory-fresh fingerprint lock."""

    def __init__(self, *, model: int = 23, fail_at: CommandId | None = None) -> None:
        self.model = model
        self.fail_at = fail_at
        self.owner_key = crypto.DEFAULT_OWNER_KEY
        self.device_id = crypto.DEFAULT_DEVICE_ID
        self.name = b""
        self.time: int | None = None
        self.server_key: bytes | None = None
        self.link: crypto.LinkKeys | None = None
        self.auth_nonce: bytes | None = None
        self.authenticated = False
        self.seen: list[CommandId] = []
        self.auth_begin_device_id: bytes | None = None
        self._reasm = protocol.Reassembler()
        self._handler: Callable[[bytes], None] | None = None
        self._loop = None

    def set_notify_handler(self, handler: Callable[[bytes], None]) -> None:
        # A new Session means a new BLE connection: the lock forgets the link.
        self._handler = handler
        self.link = None
        self.authenticated = False
        self._reasm = protocol.Reassembler()

    async def write(self, data: bytes) -> None:
        payload = self._reasm.feed(data)
        if payload is None:
            return
        if self.link is not None:
            payload = crypto.decrypt(self.link.key, self.link.iv, payload)
        cid, length, ref = payload[0], payload[1], payload[2]
        body = payload[4 : 4 + length]
        responses = self._handle(CommandId(cid), ref, body)
        loop = asyncio.get_running_loop()
        for resp in responses:
            wire = resp
            if self.link is not None and cid != CommandId.EXCHANGE_KEY_PUB_M:
                wire = crypto.encrypt(self.link.key, self.link.iv, wire)
            for frame in protocol.frame_payload(wire, encrypted=self.link is not None):
                loop.call_soon(self._handler, frame)

    @staticmethod
    def _resp(cid: int, ref: int, status: int, body: bytes = b"") -> bytes:
        return bytes([cid, len(body), ref, status]) + body

    def _handle(self, cid: CommandId, ref: int, body: bytes) -> list[bytes]:
        self.seen.append(cid)
        if cid == self.fail_at:
            return [self._resp(cid, ref, protocol.ResponseStatus.SECURITY_ERROR)]
        if cid == CommandId.EXCHANGE_KEY_PUB_M:
            private = crypto.generate_key_pair()
            self.link = crypto.LinkKeys.from_reversed_secret(
                crypto.reversed_shared_secret(private, body)
            )
            return [self._resp(cid, ref, 0, crypto.public_key_to_wire(private.public_key()))]
        assert self.link is not None
        if cid == CommandId.DEVICE_MODEL_GET:
            return [self._resp(cid, ref, 0, bytes([self.model]))]
        if cid == CommandId.USER_AUTH_BEGIN:
            self.auth_begin_device_id = body[1:7]
            self.auth_nonce = secrets.token_bytes(16)
            return [self._resp(cid, ref, 0, crypto.make_owner_challenge(self.owner_key, self.link.iv, self.auth_nonce))]
        if cid == CommandId.USER_AUTH_FINALIZE:
            assert self.auth_nonce is not None
            expected = crypto.encrypt(self.owner_key, self.link.iv, crypto.bit_invert(self.auth_nonce))
            if body != expected:
                return [self._resp(cid, ref, protocol.ResponseStatus.SECURITY_ERROR)]
            self.authenticated = True
            return [self._resp(cid, ref, 0, b"\x00")]
        if not self.authenticated:
            return [self._resp(cid, ref, protocol.ResponseStatus.SECURITY_ERROR)]
        if cid == CommandId.USER_AUTH_UPDATE:
            private = crypto.generate_key_pair()
            self.owner_key = crypto.owner_key_from_reversed_secret(
                crypto.reversed_shared_secret(private, body[2:66])
            )
            return [self._resp(cid, ref, 0, crypto.public_key_to_wire(private.public_key()))]
        if cid == CommandId.DEVICE_ID_SET:
            self.device_id = body
            return [self._resp(cid, ref, 0)]
        if cid == CommandId.CURRENT_TIME_SET:
            self.time = int.from_bytes(body, "little")
            return [self._resp(cid, ref, 0)]
        if cid == CommandId.SERVER_KEY_UPDATE:
            self.server_key = body
            private = crypto.generate_key_pair()
            return [self._resp(cid, ref, 0, crypto.public_key_to_wire(private.public_key()))]
        if cid == CommandId.DEVICE_NAME_SET:
            self.name = body
            return [self._resp(cid, ref, 0)]
        if cid == CommandId.FINGERPRINT_SCAN:
            slot = int.from_bytes(body, "little")
            event = self._resp(protocol.EventId.USER_ADDED, protocol.EVENT_REF, 0, body + b"\x03")
            return [self._resp(cid, ref, 0, body + b"\x00"), event]
        return [self._resp(cid, ref, protocol.ResponseStatus.NOT_SUPPORTED)]


def _session(lock: FakeLock) -> Session:
    return Session(lock, firmware=FW, command_delay=0, timeout=2)


async def test_preflight_handshakes_reads_model_and_default_auths() -> None:
    lock = FakeLock()
    report = await enrollment.preflight(_session(lock), lock_address="AA", firmware=FW)
    assert report["link_handshake"] is True
    assert report["model"] == "NimlyPro (23)" and report["fingerprint_capable"] is True
    assert report["default_owner_auth"] is True
    assert lock.auth_begin_device_id == bytes(6)  # all-zero id on a factory lock
    assert CommandId.USER_AUTH_UPDATE not in lock.seen  # nothing changed


async def test_enroll_requires_recent_preflight(tmp_path: Path) -> None:
    store = OwnerKeyStore(tmp_path)
    with pytest.raises(enrollment.EnrollmentRefused):
        await enrollment.enroll(_session(FakeLock()), store, lock_address="AA", name="Dor")


async def test_enroll_persists_owner_key_before_any_further_write(tmp_path: Path) -> None:
    store = OwnerKeyStore(tmp_path)
    store.mark_preflight("AA", {"default_owner_auth": True})
    lock = FakeLock(fail_at=CommandId.DEVICE_ID_SET)
    with pytest.raises(CommandFailed):
        await enrollment.enroll(_session(lock), store, lock_address="AA", name="Dor")
    record = store.load("AA")
    assert record is not None and record.stage == "owner_key_received"
    assert record.owner_key == lock.owner_key  # the key the lock now holds
    assert store.path_for("AA").stat().st_mode & 0o777 == 0o600


async def test_enroll_completes_in_the_apps_order_and_stored_key_opens_lock(tmp_path: Path) -> None:
    store = OwnerKeyStore(tmp_path)
    store.mark_preflight("AA", {"default_owner_auth": True})
    lock = FakeLock()
    record = await enrollment.enroll(
        _session(lock), store, lock_address="AA", name="Dor", now=protocol.TIME_EPOCH_UNIX + 600
    )
    assert record.stage == "enrolled"
    assert lock.seen[-5:] == [
        CommandId.USER_AUTH_UPDATE, CommandId.DEVICE_ID_SET, CommandId.CURRENT_TIME_SET,
        CommandId.SERVER_KEY_UPDATE, CommandId.DEVICE_NAME_SET,
    ]
    assert lock.device_id == record.device_id and lock.time == 10 and lock.name == b"Dor" + bytes(6)
    assert record.server_private_pem.startswith("-----BEGIN PRIVATE KEY-----")
    # A second enrollment is refused; the stored key authenticates a new session.
    with pytest.raises(enrollment.EnrollmentRefused):
        await enrollment.enroll(_session(lock), store, lock_address="AA", name="Dor")
    session = _session(lock)
    await session.handshake()
    await session.owner_authenticate(record.owner_key, user_id=0, device_id=record.device_id)
    assert lock.authenticated and lock.auth_begin_device_id == record.device_id


async def test_fingerprint_scan_uses_stored_owner_and_collects_user_added(tmp_path: Path) -> None:
    store = OwnerKeyStore(tmp_path)
    store.mark_preflight("AA", {"default_owner_auth": True})
    lock = FakeLock()
    await enrollment.enroll(_session(lock), store, lock_address="AA", name="Dor")
    result = await enrollment.fingerprint_scan(
        _session(lock), store, lock_address="AA", slot=150, event_wait=2
    )
    assert result["reported_slot"] == 150 and result["scan_status"] == "ok"
    assert result["user_added_events"] == [{"event": "user_added", "slot": 150, "status": "fingerprint"}]


async def test_fingerprint_scan_refuses_without_enrolled_record(tmp_path: Path) -> None:
    from nimly_ble.keystore import KeyStoreError
    with pytest.raises(KeyStoreError):
        await enrollment.fingerprint_scan(_session(FakeLock()), OwnerKeyStore(tmp_path), lock_address="AA", slot=150)


async def test_wrong_owner_key_is_rejected_by_lock() -> None:
    lock = FakeLock()
    session = _session(lock)
    await session.handshake()
    with pytest.raises(CommandFailed) as info:
        await session.owner_authenticate(bytes(16), user_id=0, device_id=bytes(6))
    assert info.value.response.status_name() == "SECURITY_ERROR"


def test_event_parsing() -> None:
    lock_status = Response(protocol.EventId.LOCK_STATUS, protocol.EVENT_REF, 0, b"\x96\x00\x02\x03")
    assert protocol.parse_event(lock_status) == {"event": "lock_status", "slot": 150, "state": "unlocked", "method": "fingerprint"}
