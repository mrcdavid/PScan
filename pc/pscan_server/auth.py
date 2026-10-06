"""One-time pairing (6-digit code shown on the PC) and per-phone access tokens."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CODE_LIFETIME = 120  # seconds
MAX_ATTEMPTS = 5
MAX_STARTS_PER_MINUTE = 6


class PairingError(Exception):
    pass


@dataclass
class _Pending:
    code: str
    device_name: str
    expires: float
    attempts: int = 0


@dataclass
class DeviceStore:
    """Paired phones, stored as token hashes in devices.json."""

    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _read(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []

    def _write(self, devices: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(devices, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def add(self, name: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            devices = self._read()
            devices.append({"name": name, "token_sha256": self._hash(token), "paired_at": time.time()})
            self._write(devices)
        log.info("Paired new device %r", name)
        return token

    def verify(self, token: str | None) -> dict | None:
        if not token:
            return None
        digest = self._hash(token)
        with self._lock:
            for device in self._read():
                if hmac.compare_digest(device["token_sha256"], digest):
                    return device
        return None

    def list(self) -> list[dict]:
        with self._lock:
            return [{"name": d["name"], "paired_at": d["paired_at"]} for d in self._read()]

    def forget_all(self) -> int:
        with self._lock:
            count = len(self._read())
            self._write([])
        log.info("Forgot %d paired device(s)", count)
        return count


class Pairing:
    """Pending pairing requests: the phone asks, the PC shows a code, the phone sends it back."""

    def __init__(self, devices: DeviceStore, on_code=None):
        self.devices = devices
        self.on_code = on_code  # called with (code, device_name) so the PC can display it
        self._pending: dict[str, _Pending] = {}
        self._starts: list[float] = []
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        for pid in [p for p, v in self._pending.items() if v.expires < now]:
            del self._pending[pid]
        self._starts = [t for t in self._starts if now - t < 60]

    def start(self, device_name: str) -> str:
        device_name = (device_name or "Phone").strip()[:60] or "Phone"
        now = time.time()
        with self._lock:
            self._expire(now)
            if len(self._starts) >= MAX_STARTS_PER_MINUTE:
                raise PairingError("Too many pairing requests. Wait a minute and try again.")
            self._starts.append(now)
            pair_id = secrets.token_hex(8)
            code = f"{secrets.randbelow(1_000_000):06d}"
            self._pending[pair_id] = _Pending(code, device_name, now + CODE_LIFETIME)
        log.info("Pairing requested by %r", device_name)
        if self.on_code:
            self.on_code(code, device_name)
        return pair_id

    def finish(self, pair_id: str, code: str) -> str:
        code = "".join(ch for ch in (code or "") if ch.isdigit())
        with self._lock:
            self._expire(time.time())
            pending = self._pending.get(pair_id)
            if pending is None:
                raise PairingError("This pairing request expired. Tap your PC again to get a new code.")
            if not hmac.compare_digest(pending.code, code):
                pending.attempts += 1
                if pending.attempts >= MAX_ATTEMPTS:
                    del self._pending[pair_id]
                    raise PairingError("Too many wrong codes. Tap your PC again to get a new code.")
                raise PairingError("Wrong code. Check the notification on your PC.")
            del self._pending[pair_id]
            device_name = pending.device_name
        return self.devices.add(device_name)

    def current_code(self) -> tuple[str, str] | None:
        """The newest code still waiting to be entered, as (code, device_name)."""
        with self._lock:
            self._expire(time.time())
            if not self._pending:
                return None
            newest = max(self._pending.values(), key=lambda p: p.expires)
            return newest.code, newest.device_name
