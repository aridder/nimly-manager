"""Link and owner crypto for the Nimly BLE protocol.

Transport: a fresh P-256 ECDH per connection; the raw secret is byte-reversed
and split into AES-128 key [0:16] and IV [16:32]. Every message is its own
AES-128-CBC run from that IV, zero-padded to whole blocks.

Owner auth: the 16-byte challenge is decrypted with (owner key, link IV),
bit-inverted, and re-encrypted with the same key and IV. The owner key itself
is the reversed secret [0:16] of a *fresh* key pair exchanged in
``UserAuthUpdate``. All per onesti-lock, confirmed there by a JDK run of the
app's own classes.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CURVE = ec.SECP256R1()
COORD_BYTES = 32
WIRE_PUBLIC_KEY_BYTES = 64
BLOCK = 16

# Factory owner credential on a lock never enrolled over BLE. The IV constant
# the app also defines is never read by anything, so it is omitted here.
DEFAULT_OWNER_KEY = bytes([0x11]) * 16
DEFAULT_DEVICE_ID = bytes(6)
DEFAULT_ADMIN_USER_ID = 0


def generate_key_pair() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(CURVE)


def public_key_to_wire(key: ec.EllipticCurvePublicKey) -> bytes:
    """X then Y, 32 bytes each, little endian per coordinate."""

    numbers = key.public_numbers()
    return numbers.x.to_bytes(COORD_BYTES, "little") + numbers.y.to_bytes(
        COORD_BYTES, "little"
    )


def public_key_from_wire(data: bytes) -> ec.EllipticCurvePublicKey:
    if len(data) != WIRE_PUBLIC_KEY_BYTES:
        raise ValueError(f"wire public key must be 64 bytes, got {len(data)}")
    x = int.from_bytes(data[:COORD_BYTES], "little")
    y = int.from_bytes(data[COORD_BYTES:], "little")
    return ec.EllipticCurvePublicNumbers(x, y, CURVE).public_key()


def reversed_shared_secret(
    private: ec.EllipticCurvePrivateKey, peer_wire: bytes
) -> bytes:
    """The 32-byte ECDH secret, byte-reversed as the app does it.

    ``cryptography`` always returns the full 32 bytes with leading zeros kept,
    which the reversal depends on.
    """

    secret = private.exchange(ec.ECDH(), public_key_from_wire(peer_wire))
    assert len(secret) == 32
    return secret[::-1]


@dataclass(frozen=True, slots=True)
class LinkKeys:
    key: bytes
    iv: bytes

    @classmethod
    def from_reversed_secret(cls, reversed_secret: bytes) -> LinkKeys:
        return cls(key=reversed_secret[:16], iv=reversed_secret[16:32])


def owner_key_from_reversed_secret(reversed_secret: bytes) -> bytes:
    """The owner key is the first 16 bytes of the reversed secret."""

    return reversed_secret[:16]


def _cbc(key: bytes, iv: bytes) -> Cipher:
    return Cipher(algorithms.AES(key), modes.CBC(iv))


def zero_pad(data: bytes) -> bytes:
    remainder = len(data) % BLOCK
    return data if remainder == 0 else data + bytes(BLOCK - remainder)


def encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    """One CBC run from ``iv``; zero-pads; an empty message stays empty."""

    if not plaintext:
        return b""
    encryptor = _cbc(key, iv).encryptor()
    return encryptor.update(zero_pad(plaintext)) + encryptor.finalize()


def decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """One CBC run from ``iv``; returns padding with the plaintext.

    The layer-2/3 length field says where the real message ends.
    """

    if not ciphertext:
        return b""
    if len(ciphertext) % BLOCK:
        raise ValueError("ciphertext length is not a multiple of 16")
    decryptor = _cbc(key, iv).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def bit_invert(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


def owner_auth_answer(owner_key: bytes, link_iv: bytes, challenge: bytes) -> bytes:
    """decrypt → invert every bit → encrypt, all with (owner key, link IV)."""

    if len(challenge) != BLOCK:
        raise ValueError("owner-auth challenge must be 16 bytes")
    plain = decrypt(owner_key, link_iv, challenge)
    return encrypt(owner_key, link_iv, bit_invert(plain))


def make_owner_challenge(owner_key: bytes, link_iv: bytes, nonce: bytes) -> bytes:
    """What a lock sends: its 16-byte nonce encrypted under the owner key.

    Inferred from the app decrypting it this way; used by the test fake lock.
    """

    if len(nonce) != BLOCK:
        raise ValueError("nonce must be 16 bytes")
    return encrypt(owner_key, link_iv, nonce)
