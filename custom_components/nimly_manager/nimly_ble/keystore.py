"""Durable, write-ahead storage for the owner credential.

After ``UserAuthUpdate`` the lock's default key presumably stops working, so
the derived owner key must be on disk — fsynced — before anything else is
sent. Losing it means a module reset and a Zigbee re-pair. The file lives in
the user's config dir, mode 0600, never in a repo or a scratch dir.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_DIR = Path("~/.config/nimly-manager").expanduser()
PREFLIGHT_VALID_SECONDS = 30 * 60


class KeyStoreError(RuntimeError):
    pass


@dataclass(slots=True)
class OwnerRecord:
    lock_address: str
    device_id_hex: str
    owner_key_hex: str = field(repr=False)
    stage: str = "owner_key_received"  # owner_key_received | enrolled
    server_private_pem: str = field(default="", repr=False)
    name: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    @property
    def owner_key(self) -> bytes:
        return bytes.fromhex(self.owner_key_hex)

    @property
    def device_id(self) -> bytes:
        return bytes.fromhex(self.device_id_hex)

    def as_dict(self) -> dict[str, object]:
        """Full record for a private store. Never log or expose the result."""

        return asdict(self)

    def public_dict(self) -> dict[str, object]:
        """What a UI or diagnostics may see: no key, no server key."""

        return {
            "lock_address": self.lock_address,
            "name": self.name,
            "stage": self.stage,
            "created": self.created,
            "updated": self.updated,
        }


def owner_record_from_json(text: str) -> OwnerRecord:
    """Parse and validate the content of an ``owner-<adresse>.json`` file.

    Used for the one-time import into Home Assistant. Refuses anything that
    is not a complete, *enrolled* record, so a half-written or preflight
    file can never masquerade as an owner credential.
    """

    try:
        data = json.loads(text)
    except ValueError as error:
        raise KeyStoreError("ugyldig JSON") from error
    if not isinstance(data, dict):
        raise KeyStoreError("eierposten må være et JSON-objekt")
    try:
        record = OwnerRecord(
            lock_address=str(data["lock_address"]),
            device_id_hex=str(data["device_id_hex"]).lower(),
            owner_key_hex=str(data["owner_key_hex"]).lower(),
            stage=str(data["stage"]),
            server_private_pem=str(data.get("server_private_pem", "")),
            name=str(data.get("name", "")),
            created=float(data.get("created", time.time())),
            updated=float(data.get("updated", time.time())),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise KeyStoreError("eierposten mangler felt") from error
    if not _is_hex(record.owner_key_hex, 32):
        raise KeyStoreError("owner_key_hex må være 16 byte hex")
    if not _is_hex(record.device_id_hex, 12):
        raise KeyStoreError("device_id_hex må være 6 byte hex")
    if record.stage != "enrolled":
        raise KeyStoreError(
            f"eierposten er ikke ferdig enrollet (stage={record.stage})"
        )
    return record


def _is_hex(value: str, length: int) -> bool:
    if len(value) != length:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


class OwnerKeyStore:
    """One JSON file per lock address under the config dir."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or DEFAULT_DIR

    def path_for(self, lock_address: str) -> Path:
        safe = lock_address.replace(":", "").replace("-", "").lower() or "unknown"
        return self.directory / f"owner-{safe}.json"

    def preflight_path(self, lock_address: str) -> Path:
        return self.path_for(lock_address).with_name(
            self.path_for(lock_address).stem + ".preflight.json"
        )

    def save(self, record: OwnerRecord) -> Path:
        record.updated = time.time()
        path = self.path_for(record.lock_address)
        _atomic_write(path, record.as_dict())
        return path

    def load(self, lock_address: str) -> OwnerRecord | None:
        path = self.path_for(lock_address)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return OwnerRecord(**data)

    def exists(self, lock_address: str) -> bool:
        return self.path_for(lock_address).exists()

    def mark_preflight(self, lock_address: str, report: dict[str, object]) -> Path:
        path = self.preflight_path(lock_address)
        _atomic_write(path, {"at": time.time(), "report": report})
        return path

    def preflight_passed_recently(self, lock_address: str) -> bool:
        path = self.preflight_path(lock_address)
        if not path.exists():
            return False
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        at = data.get("at", 0)
        ok = bool(data.get("report", {}).get("default_owner_auth"))
        return ok and (time.time() - float(at)) <= PREFLIGHT_VALID_SECONDS
