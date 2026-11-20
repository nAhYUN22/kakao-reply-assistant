"""Explicit macOS Keychain access. Missing or inaccessible keys never fall back."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import hmac
import os
from pathlib import Path
import platform
import re
import threading
from typing import Protocol


class KeyStoreError(ValueError):
    """Non-sensitive key lifecycle error; original backend text is suppressed."""


class KeyProvider(Protocol):
    def get_key(self, key_id: str) -> bytes: ...


def _checked_id(key_id: str) -> str:
    if not isinstance(key_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", key_id):
        raise KeyStoreError("INVALID_KEY_REFERENCE")
    return key_id


class EphemeralKeyProvider:
    """Synthetic tests only; a new provider cannot reopen another provider's keys."""
    kind = "ephemeral_mock"

    def __init__(self):
        self._keys: dict[str, bytes] = {}

    def __repr__(self) -> str:
        return "EphemeralKeyProvider(synthetic_only=True)"

    def provision(self, key_id: str) -> bytes:
        key_id = _checked_id(key_id)
        if key_id not in self._keys:
            self._keys[key_id] = os.urandom(32)
        return self._keys[key_id]

    def get_key(self, key_id: str) -> bytes:
        key_id = _checked_id(key_id)
        if key_id not in self._keys:
            raise KeyStoreError("KEY_NOT_FOUND")
        return self._keys[key_id]


class MacOSKeychainProvider:
    """Use only keyring's macOS backend, not its automatic backend selection.

    Constructing this provider performs no Keychain reads or writes. `get_key`
    accesses an existing item. `provision` is an explicit setup operation.
    All KakaoReply provisioners must use the default lock path so that the
    keyring backend's replace operation cannot race between app processes.
    The injectable backend/lock path exist for synthetic tests, not fallback.
    """

    kind = "keychain"
    SERVICE = "KakaoReply.Encryption.v1"
    _thread_lock = threading.RLock()

    def __init__(self, *, backend=None, lock_path: str | Path | None = None):
        if platform.system() != "Darwin":
            raise KeyStoreError("KEYCHAIN_UNSUPPORTED_PLATFORM")
        if backend is None:
            try:
                from keyring.backends.macOS import Keyring
                backend = Keyring()
                # A custom KEYCHAIN_PATH can cause warnings containing local paths.
                # KakaoReply uses the standard user keychain, not an environment override.
                backend.keychain = None
            except Exception:
                raise KeyStoreError("KEYCHAIN_UNAVAILABLE") from None
        self._backend = backend
        self._lock_path = Path(lock_path) if lock_path is not None else (
            Path.home() / "Library/Application Support/KakaoReply/key-provision.lock"
        )

    def __repr__(self) -> str:
        return "MacOSKeychainProvider()"

    @staticmethod
    def _decode(value) -> bytes:
        try:
            if not isinstance(value, str):
                raise ValueError
            key = base64.b64decode(value.encode("ascii"), validate=True)
            if len(key) != 32:
                raise ValueError
            return key
        except Exception:
            raise KeyStoreError("KEYCHAIN_INVALID_KEY") from None

    def _read(self, key_id: str):
        try:
            return self._backend.get_password(self.SERVICE, key_id)
        except Exception:
            raise KeyStoreError("KEYCHAIN_ACCESS_FAILED") from None

    def get_key(self, key_id: str) -> bytes:
        value = self._read(_checked_id(key_id))
        if value is None:
            raise KeyStoreError("KEY_NOT_FOUND")
        return self._decode(value)

    @contextmanager
    def _provision_lock(self):
        descriptor = None
        try:
            self._lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(self._lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            raise KeyStoreError("KEY_PROVISION_LOCK_UNAVAILABLE") from None
        try:
            yield
        finally:
            os.close(descriptor)

    def provision(self, key_id: str) -> bytes:
        key_id = _checked_id(key_id)
        with self._thread_lock, self._provision_lock():
            existing = self._read(key_id)
            if existing is not None:
                # Invalid existing values are never replaced automatically.
                return self._decode(existing)
            key = os.urandom(32)
            encoded = base64.b64encode(key).decode("ascii")
            try:
                self._backend.set_password(self.SERVICE, key_id, encoded)
            except Exception:
                raise KeyStoreError("KEYCHAIN_WRITE_FAILED") from None
            saved = self.get_key(key_id)
            if not hmac.compare_digest(saved, key):
                raise KeyStoreError("KEYCHAIN_VERIFICATION_FAILED")
            return saved
