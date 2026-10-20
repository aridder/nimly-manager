"""Independent vectors: NIST CAVS/SP800-38A plus the vendor app's own crypto
classes run on a JDK, as published in fredrik-lindseth/onesti-lock
(tests/ble/crypto_vectors.py, MIT). Nothing here was captured from a lock;
these prove two implementations agree, not that the lock does.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric import ec

from nimly_ble import crypto, protocol
from nimly_ble.protocol import Command, CommandId

H = bytes.fromhex

CAVS_D_IUT = H("7d7dc5f71eb29ddaf80d6214632eeae03d9058af1fb6d22ed80badb62bc1a534")
CAVS_OWN_PUBLIC_WIRE = H(
    "30b2a6d881d25e38ce387df9bbedc47017a69cf86f14296b87e819015918d2ea"
    "415140e1fced599f38258364e66eb09c425ac8ac232500a72f5ed31f2861af28"
)
CAVS_PEER_PUBLIC_WIRE = H(
    "87d2338883cce72cb4f64d3aceac6b1bb90d6465ca32c65c4c58567ff7480c70"
    "aca45fb8ca821744e0df40f6fb468d94c5dc515cba20db0d069bfde309e571db"
)
CAVS_SHARED_SECRET_REVERSED = H("7bbd978977d70d04681e56602085c5cc252dddfb34a4542e01ff20641062fc46")
CAVS_LINK_KEY = H("7bbd978977d70d04681e56602085c5cc")
CAVS_LINK_IV = H("252dddfb34a4542e01ff20641062fc46")

AES_KEY = H("2b7e151628aed2a6abf7158809cf4f3c")
AES_IV = H("000102030405060708090a0b0c0d0e0f")
AES_PLAINTEXT = H(
    "6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51"
    "30c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710"
)
AES_CBC_CIPHERTEXT = H(
    "7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2"
    "73bed6b8e3c1743b7116e69e222295163ff1caa1681fac09120eca307586e1a7"
)
OWNER_CHALLENGE = H("00112233445566778899aabbccddeeff")
OWNER_ANSWER_DEFAULT_KEY = H("a2cbc9d9b56c2df7b8f15917ce44d566")


def test_cavs_ecdh_wire_encoding_and_reversed_secret() -> None:
    private = ec.derive_private_key(int.from_bytes(CAVS_D_IUT, "big"), crypto.CURVE)
    assert crypto.public_key_to_wire(private.public_key()) == CAVS_OWN_PUBLIC_WIRE
    reversed_secret = crypto.reversed_shared_secret(private, CAVS_PEER_PUBLIC_WIRE)
    assert reversed_secret == CAVS_SHARED_SECRET_REVERSED
    link = crypto.LinkKeys.from_reversed_secret(reversed_secret)
    assert link.key == CAVS_LINK_KEY and link.iv == CAVS_LINK_IV


def test_sp800_38a_cbc_and_app_zero_padding() -> None:
    assert crypto.encrypt(AES_KEY, AES_IV, AES_PLAINTEXT) == AES_CBC_CIPHERTEXT
    assert crypto.decrypt(AES_KEY, AES_IV, AES_CBC_CIPHERTEXT) == AES_PLAINTEXT
    assert crypto.encrypt(AES_KEY, AES_IV, H("0102030405")) == H("2d971c5ddabf641d9a013db4f06d296f")
    assert crypto.encrypt(AES_KEY, AES_IV, H("000102030405060708090a0b0c0d0e0f10")) == H(
        "7df76b0c1ab899b33e42f047b91b546f09961489d1984ceac1b48410a277fbeb"
    )


def test_owner_answer_matches_app_classes_on_jdk() -> None:
    answer = crypto.owner_auth_answer(crypto.DEFAULT_OWNER_KEY, AES_IV, OWNER_CHALLENGE)
    assert answer == OWNER_ANSWER_DEFAULT_KEY


def test_frame_vectors_for_handshake_and_one_encrypted_block() -> None:
    key = bytes(range(64))
    payload = Command(CommandId.EXCHANGE_KEY_PUB_M, 1, key).to_bytes()
    assert payload[:4] == H("01400100")
    frames = protocol.frame_payload(payload, encrypted=False)
    assert frames[0] == H("0310000100440000") + payload[:12]
    assert frames[1] == H("04100002") + payload[12:28]
    assert frames[3] == H("04100004") + payload[44:60]
    assert frames[4] == H("05080005") + payload[60:68]
    enc = bytes(range(16))
    frames = protocol.frame_payload(enc, encrypted=True)
    assert frames[0] == H("0310000101100000") + enc[:12]
    assert frames[1] == H("05040002") + enc[12:]
    assert protocol.user_auth_begin_payload(0, bytes(6)) == H("00000000000000")
    assert Command(CommandId.USER_AUTH_BEGIN, 1, protocol.user_auth_begin_payload(0, bytes(6))).to_bytes() == H("22070100") + bytes(7)
    assert protocol.device_name_payload("Door") == b"Door" + bytes(5)
    assert (0x12345678).to_bytes(4, "little") == H("78563412")
