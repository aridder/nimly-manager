"""Wire framing for the Nimly BLE protocol: packets, blobs, commands, responses.

Three layers, all little endian:

- Layer 1 ``Packet``: ``[type][len][rfu][seq][payload]``. Anything over 12
  payload bytes goes as a blob (BlobStart, BlobStream*, BlobComplete).
- Layer 2 ``Command``: ``[id][len][ref][rfu][payload]``.
- Layer 3 ``Response``: ``[id][len][ref][status][payload]``.

Chunk sizes mimic the app's MTU-23 framing (12 bytes in BlobStart, 16 after)
regardless of what the host negotiates: the lock's reassembly has only ever
been exercised by that framing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

SINGLE_MAX_PAYLOAD = 12
BLOB_FIRST_CHUNK = 12
BLOB_CHUNK = 16
EVENT_REF = 0x80


class PacketType(IntEnum):
    SINGLE = 0x01
    SINGLE_ENCRYPTED = 0x02
    BLOB_START = 0x03
    BLOB_STREAM = 0x04
    BLOB_COMPLETE = 0x05
    ACK = 0x06
    NAC = 0x07
    ERROR = 0xF0


class CommandId(IntEnum):
    EXCHANGE_KEY_PUB_M = 0x01
    USER_AUTH_BEGIN = 0x22
    USER_AUTH_FINALIZE = 0x23
    USER_AUTH_UPDATE = 0x24
    DEVICE_ID_SET = 0x30
    DEVICE_ID_GET = 0x31
    DEVICE_NAME_SET = 0x32
    DEVICE_NAME_GET = 0x33
    CURRENT_TIME_GET = 0x40
    CURRENT_TIME_SET = 0x41
    SERVER_KEY_UPDATE = 0x42
    DEVICE_LOG_GET = 0x44
    FINGERPRINT_SCAN = 0x57
    BATT_INFO_GET = 0x5D
    DEVICE_MODEL_GET = 0x62


class ResponseStatus(IntEnum):
    SUCCESS = 0
    FAILED = 1
    NOT_AVAILABLE = 2
    INTERNAL_ERROR = 3
    PARAMETER_ERROR = 4
    LENGTH_ERROR = 5
    NOT_FOUND = 6
    NO_MATCH = 7
    NOT_SUPPORTED = 8
    NOT_VALID = 9
    SECURITY_ERROR = 10


class EventId(IntEnum):
    USER_ADDED = 0x14
    LOCK_STATUS = 0x60


# Model byte → (name, fingerprint capable). Unknown reads as (Unknown, False).
LOCK_MODELS: dict[int, tuple[str, bool]] = {
    8: ("EasyFingerTouch", True),
    9: ("EasyCodeTouch", False),
    21: ("NimlyCode", False),
    22: ("NimlyTouch", False),
    23: ("NimlyPro", True),
    24: ("NimlyIndoor", False),
    26: ("NimlyKeybox", False),
    27: ("NimlyTwist", False),
    31: ("NimlyCode2", False),
    32: ("NimlyTouch2", False),
    33: ("NimlyPro24", True),
    34: ("NimlyIndoor2", False),
    36: ("NimlyKeybox2", False),
    37: ("NimlyTwist2", False),
}

FINGERPRINT_SLOT_MIN = 150
FINGERPRINT_SLOT_MAX = 199


class ProtocolError(ValueError):
    """Malformed frame or a response the protocol does not allow."""


# ---------------------------------------------------------------- layer 1

@dataclass(frozen=True, slots=True)
class Packet:
    type: PacketType
    seq: int
    payload: bytes

    def to_bytes(self) -> bytes:
        if len(self.payload) > 255:
            raise ProtocolError("packet payload over 255 bytes")
        return bytes([self.type, len(self.payload), 0, self.seq]) + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> Packet:
        if len(data) < 4:
            raise ProtocolError("packet shorter than its header")
        try:
            kind = PacketType(data[0])
        except ValueError as error:
            raise ProtocolError(f"unknown packet type 0x{data[0]:02x}") from error
        length = data[1]
        if len(data) < 4 + length:
            raise ProtocolError("packet shorter than its declared length")
        # Bytes past the declared length are ignored, as the app does.
        return cls(kind, data[3], bytes(data[4 : 4 + length]))


def frame_payload(payload: bytes, *, encrypted: bool) -> list[bytes]:
    """Cut one layer-2/3 payload into the packets that carry it."""

    if len(payload) <= SINGLE_MAX_PAYLOAD:
        kind = PacketType.SINGLE_ENCRYPTED if encrypted else PacketType.SINGLE
        return [Packet(kind, 1, payload).to_bytes()]

    flags = 0x01 if encrypted else 0x00
    head = bytes([flags]) + len(payload).to_bytes(2, "little") + b"\x00"
    first, rest = payload[:BLOB_FIRST_CHUNK], payload[BLOB_FIRST_CHUNK:]
    chunks = [rest[i : i + BLOB_CHUNK] for i in range(0, len(rest), BLOB_CHUNK)]

    packets = [Packet(PacketType.BLOB_START, 1, head + first)]
    seq = 2
    # Every chunk but the last streams; the last one rides in BlobComplete.
    for chunk in chunks[:-1]:
        packets.append(Packet(PacketType.BLOB_STREAM, seq, chunk))
        seq += 1
    packets.append(Packet(PacketType.BLOB_COMPLETE, seq, chunks[-1] if chunks else b""))
    return [p.to_bytes() for p in packets]


class Reassembler:
    """Collect packets into whole payloads; one payload at a time."""

    def __init__(self) -> None:
        self._buffer: bytearray | None = None
        self._expected_total = 0
        self._next_seq = 0

    def feed(self, data: bytes) -> bytes | None:
        """Return a complete payload when this packet finishes one."""

        packet = Packet.from_bytes(data)
        if packet.type in (PacketType.SINGLE, PacketType.SINGLE_ENCRYPTED):
            self._buffer = None
            return packet.payload

        if packet.type == PacketType.BLOB_START:
            if len(packet.payload) < 4:
                raise ProtocolError("BlobStart shorter than its header")
            self._expected_total = int.from_bytes(packet.payload[1:3], "little")
            self._buffer = bytearray(packet.payload[4:])
            self._next_seq = (packet.seq + 1) & 0xFF
            return self._finish_if_done(final=False)

        if packet.type in (PacketType.BLOB_STREAM, PacketType.BLOB_COMPLETE):
            if self._buffer is None:
                raise ProtocolError("blob continuation without BlobStart")
            if packet.seq != self._next_seq:
                raise ProtocolError(
                    f"blob sequence {packet.seq} != expected {self._next_seq}"
                )
            self._next_seq = (self._next_seq + 1) & 0xFF
            self._buffer.extend(packet.payload)
            return self._finish_if_done(final=packet.type == PacketType.BLOB_COMPLETE)

        # Ack/Nac/Error: the app never waits for these; surface as empty.
        return None

    def _finish_if_done(self, *, final: bool) -> bytes | None:
        assert self._buffer is not None
        if not final:
            return None
        if len(self._buffer) != self._expected_total:
            raise ProtocolError(
                f"blob total {len(self._buffer)} != declared {self._expected_total}"
            )
        payload = bytes(self._buffer)
        self._buffer = None
        return payload


# ---------------------------------------------------------------- layer 2/3

@dataclass(frozen=True, slots=True)
class Command:
    id: CommandId
    ref: int
    payload: bytes = b""

    def to_bytes(self) -> bytes:
        if not 1 <= self.ref <= 254:
            raise ProtocolError("command ref must be 1..254")
        if len(self.payload) > 255:
            raise ProtocolError("command payload over 255 bytes")
        return bytes([self.id, len(self.payload), self.ref, 0]) + self.payload


@dataclass(frozen=True, slots=True)
class Response:
    id: int
    ref: int
    status: int
    payload: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> Response:
        if len(data) < 4:
            raise ProtocolError("response shorter than its header")
        length = data[1]
        if len(data) < 4 + length:
            raise ProtocolError("response shorter than its declared length")
        # Exactly ``length`` payload bytes; CBC zero-padding beyond is ignored.
        return cls(data[0], data[2], data[3], bytes(data[4 : 4 + length]))

    @property
    def ok(self) -> bool:
        return self.status == ResponseStatus.SUCCESS

    @property
    def is_event(self) -> bool:
        return self.ref == EVENT_REF

    def status_name(self) -> str:
        try:
            return ResponseStatus(self.status).name
        except ValueError:
            return f"UNKNOWN_{self.status}"


class CommandRefCounter:
    """1..127 wrapping to 1 (firmware ≥ 4.7.90); a fixed 16 below that."""

    def __init__(self, *, counting: bool) -> None:
        self._counting = counting
        self._next = 1

    def next(self) -> int:
        if not self._counting:
            return 16
        ref = self._next
        self._next = 1 if ref >= 127 else ref + 1
        return ref


# ---------------------------------------------------------------- payloads

TIME_EPOCH_UNIX = 1672531200  # 2023-01-01T00:00:00Z


def minutes_since_epoch(unix_seconds: float) -> int:
    minutes = int((unix_seconds - TIME_EPOCH_UNIX) // 60)
    if minutes < 0:
        raise ProtocolError("time before the 2023-01-01 protocol epoch")
    if minutes > 0xFFFFFFFF:
        raise ProtocolError("time overflows uint32 minutes")
    return minutes


def user_auth_begin_payload(user_id: int, device_id: bytes) -> bytes:
    if len(device_id) != 6:
        raise ProtocolError("device id must be 6 bytes")
    return bytes([user_id]) + device_id


def user_auth_update_payload(user_id: int, credentials: int, wire_public: bytes) -> bytes:
    if len(wire_public) != 64:
        raise ProtocolError("public key must be 64 wire bytes")
    return bytes([user_id, credentials]) + wire_public


def device_id_payload(device_id: bytes) -> bytes:
    if len(device_id) != 6:
        raise ProtocolError("device id must be 6 bytes")
    return device_id


def device_name_payload(name: str) -> bytes:
    raw = name.encode("ascii", errors="strict")[:8]
    return raw.ljust(9, b"\x00")


def current_time_payload(unix_seconds: float) -> bytes:
    return minutes_since_epoch(unix_seconds).to_bytes(4, "little")


def server_key_payload(wire_public: bytes) -> bytes:
    if len(wire_public) != 64:
        raise ProtocolError("server public key must be 64 wire bytes")
    return wire_public


def fingerprint_slot_payload(slot: int) -> bytes:
    if not FINGERPRINT_SLOT_MIN <= slot <= FINGERPRINT_SLOT_MAX:
        raise ProtocolError(
            f"fingerprint slot must be {FINGERPRINT_SLOT_MIN}..{FINGERPRINT_SLOT_MAX}"
        )
    return slot.to_bytes(2, "little")


def parse_model(payload: bytes) -> tuple[int, str, bool]:
    model = payload[0] if payload else 0
    name, fingerprint = LOCK_MODELS.get(model, ("Unknown", False))
    return model, name, fingerprint


def parse_battery(payload: bytes) -> dict[str, int | bool]:
    if len(payload) < 4:
        raise ProtocolError("battery payload shorter than 4 bytes")
    return {
        "level": int.from_bytes(payload[0:2], "little"),
        "low": payload[2] == 1,
        "percent": payload[3],
    }


def parse_fingerprint_scan(payload: bytes) -> tuple[int, int]:
    if len(payload) < 3:
        raise ProtocolError("fingerprint scan payload shorter than 3 bytes")
    return int.from_bytes(payload[0:2], "little"), payload[2]


def parse_event(response: Response) -> dict[str, object]:
    if response.id == EventId.LOCK_STATUS and len(response.payload) >= 4:
        state = {1: "locked", 2: "unlocked"}.get(response.payload[2], "unknown")
        method = {
            0: "key", 1: "button", 2: "panel", 3: "fingerprint", 4: "rfid", 5: "other"
        }.get(response.payload[3], "unknown")
        return {
            "event": "lock_status",
            "slot": int.from_bytes(response.payload[0:2], "little"),
            "state": state,
            "method": method,
        }
    if response.id == EventId.USER_ADDED and len(response.payload) >= 3:
        status = {
            0: "not_added", 1: "pin", 2: "rfid", 3: "fingerprint", 4: "slot_occupied"
        }.get(response.payload[2], "unknown")
        return {
            "event": "user_added",
            "slot": int.from_bytes(response.payload[0:2], "little"),
            "status": status,
        }
    return {"event": "unknown", "id": response.id}
