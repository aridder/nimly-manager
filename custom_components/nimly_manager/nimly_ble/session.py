"""One BLE conversation with a lock: handshake, encrypted commands, events.

Transport-agnostic so the same session runs over bleak on a laptop and over
Home Assistant's bluetooth integration (and its ESPHome proxies) later.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

from . import crypto, protocol
from .protocol import Command, CommandId, ProtocolError, Response

_LOGGER = logging.getLogger(__name__)

COMMAND_DELAY_SECONDS = 0.32
RESPONSE_TIMEOUT_SECONDS = 20.0
REF_COUNTER_FIRMWARE = (4, 7, 90)


class Transport(Protocol):
    async def write(self, data: bytes) -> None: ...
    def set_notify_handler(self, handler: Callable[[bytes], None]) -> None: ...


class SessionError(RuntimeError):
    pass


class CommandFailed(SessionError):
    def __init__(self, command: CommandId, response: Response) -> None:
        super().__init__(f"{command.name} → {response.status_name()}")
        self.command = command
        self.response = response


class Session:
    def __init__(
        self,
        transport: Transport,
        *,
        firmware: tuple[int, int, int],
        command_delay: float = COMMAND_DELAY_SECONDS,
        timeout: float = RESPONSE_TIMEOUT_SECONDS,
    ) -> None:
        self._transport = transport
        self._refs = protocol.CommandRefCounter(
            counting=firmware >= REF_COUNTER_FIRMWARE
        )
        self._delay = command_delay
        self._timeout = timeout
        self._reassembler = protocol.Reassembler()
        self._link: crypto.LinkKeys | None = None
        self._pending: dict[int, asyncio.Future[Response]] = {}
        self._events: list[dict[str, object]] = []
        self._lock = asyncio.Lock()
        transport.set_notify_handler(self._on_notify)

    # ----------------------------------------------------------- inbound

    @property
    def link(self) -> crypto.LinkKeys | None:
        return self._link

    @property
    def events(self) -> list[dict[str, object]]:
        return list(self._events)

    def _on_notify(self, data: bytes) -> None:
        try:
            payload = self._reassembler.feed(data)
        except ProtocolError as error:
            _LOGGER.warning("dropping frame: %s", error)
            return
        if payload is None:
            return
        if self._link is not None:
            try:
                payload = crypto.decrypt(self._link.key, self._link.iv, payload)
            except ValueError as error:
                _LOGGER.warning("undecryptable payload: %s", error)
                return
        try:
            response = Response.from_bytes(payload)
        except ProtocolError as error:
            _LOGGER.warning("malformed response: %s", error)
            return
        if response.is_event:
            self._events.append(protocol.parse_event(response))
            return
        future = self._pending.pop(response.ref, None)
        if future is None or future.done():
            _LOGGER.debug("response for unknown ref %s", response.ref)
            return
        future.set_result(response)

    # ---------------------------------------------------------- outbound

    async def _send_raw(self, command: Command) -> Response:
        wire = command.to_bytes()
        encrypted = self._link is not None
        if self._link is not None:
            wire = crypto.encrypt(self._link.key, self._link.iv, wire)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Response] = loop.create_future()
        self._pending[command.ref] = future
        try:
            for packet in protocol.frame_payload(wire, encrypted=encrypted):
                await self._transport.write(packet)
            return await asyncio.wait_for(future, self._timeout)
        finally:
            self._pending.pop(command.ref, None)

    async def send(self, command_id: CommandId, payload: bytes = b"") -> Response:
        """Send one command and return its successful response."""

        async with self._lock:
            response = await self._send_raw(
                Command(command_id, self._refs.next(), payload)
            )
            # The app waits 320 ms after a matched answer before the next one.
            await asyncio.sleep(self._delay)
        if not response.ok:
            raise CommandFailed(command_id, response)
        return response

    # ------------------------------------------------------------- flows

    async def handshake(self) -> None:
        """Fresh ECDH; from here every payload is AES-128-CBC."""

        if self._link is not None:
            raise SessionError("handshake already done")
        private = crypto.generate_key_pair()
        response = await self.send(
            CommandId.EXCHANGE_KEY_PUB_M,
            crypto.public_key_to_wire(private.public_key()),
        )
        reversed_secret = crypto.reversed_shared_secret(private, response.payload)
        self._link = crypto.LinkKeys.from_reversed_secret(reversed_secret)

    async def owner_authenticate(
        self, owner_key: bytes, *, user_id: int, device_id: bytes
    ) -> None:
        if self._link is None:
            raise SessionError("owner auth needs the link handshake first")
        begin = await self.send(
            CommandId.USER_AUTH_BEGIN,
            protocol.user_auth_begin_payload(user_id, device_id),
        )
        answer = crypto.owner_auth_answer(owner_key, self._link.iv, begin.payload)
        await self.send(CommandId.USER_AUTH_FINALIZE, answer)

    async def owner_update(self, *, user_id: int = 0, credentials: int = 0) -> bytes:
        """Replace the owner key; returns the new 16-byte key. Irreversible."""

        if self._link is None:
            raise SessionError("owner update needs the link handshake first")
        private = crypto.generate_key_pair()
        response = await self.send(
            CommandId.USER_AUTH_UPDATE,
            protocol.user_auth_update_payload(
                user_id, credentials, crypto.public_key_to_wire(private.public_key())
            ),
        )
        reversed_secret = crypto.reversed_shared_secret(private, response.payload)
        return crypto.owner_key_from_reversed_secret(reversed_secret)
