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
    owner_key_hex: str
    stage: str  # owner_key_received | enrolled
    server_private_pem: str = ""
    name: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    @property
    def owner_key(self) -> bytes:
        return bytes.fromhex(self.owner_key_hex)

    @property
    def device_id(self) -> bytes:
        return bytes.fromhex(self.device_id_hex)


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
        _atomic_write(path, asdict(record))
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
