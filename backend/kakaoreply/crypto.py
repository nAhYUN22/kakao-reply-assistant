"""Versioned authenticated encryption; never serialize key material or plaintext errors."""
from __future__ import annotations

import hashlib
import hmac
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class CryptoError(ValueError):
    """A fixed, non-sensitive failure code safe for the API error boundary."""


class DataCipher:
    """AES-256-GCM envelope with an independent HKDF-derived HMAC key.

    Envelope: 4-byte format marker, 12-byte nonce, ciphertext and 16-byte GCM tag.
    Table, row identity, envelope version and key reference are authenticated AAD.
    Key references belong in trusted repository metadata, never in LLM output.
    """

    __slots__ = ("_aead", "_digest_key", "key_id")
    _MAGIC = b"KRE1"
    _VERSION = 1

    def __init__(self, key: bytes, key_id: str):
        if not isinstance(key, bytes) or len(key) != 32:
            raise CryptoError("INVALID_ENCRYPTION_KEY")
        if not isinstance(key_id, str) or not key_id or len(key_id) > 100:
            raise CryptoError("INVALID_KEY_REFERENCE")
        self.key_id = key_id
        self._aead = AESGCM(key)
        self._digest_key = HKDF(
            algorithm=hashes.SHA256(), length=32,
            salt=b"KakaoReply/HMAC/v1", info=b"event-and-snapshot-digest",
        ).derive(key)

    def __repr__(self) -> str:
        return "DataCipher(AES-256-GCM, version=1)"

    def _aad(self, table: str, row_id: str) -> bytes:
        if any(not isinstance(value, str) or not value or len(value) > 1000 for value in (table, row_id)):
            raise CryptoError("INVALID_ENCRYPTION_CONTEXT")
        try:
            return json.dumps(
                ["KakaoReply", self._VERSION, self.key_id, table, row_id],
                separators=(",", ":"), ensure_ascii=True,
            ).encode("ascii")
        except Exception:
            raise CryptoError("INVALID_ENCRYPTION_CONTEXT") from None

    def encrypt(self, table: str, row_id: str, plaintext: str) -> bytes:
        aad = self._aad(table, row_id)
        if not isinstance(plaintext, str):
            raise CryptoError("INVALID_PLAINTEXT")
        try:
            nonce = os.urandom(12)
            encrypted = self._aead.encrypt(nonce, plaintext.encode("utf-8"), aad)
            return self._MAGIC + nonce + encrypted
        except Exception:
            raise CryptoError("ENCRYPTION_FAILED") from None

    def decrypt(self, table: str, row_id: str, payload: bytes) -> str:
        aad = self._aad(table, row_id)
        if not isinstance(payload, bytes) or len(payload) < 32 or payload[:4] != self._MAGIC:
            raise CryptoError("INVALID_ENCRYPTED_PAYLOAD")
        try:
            return self._aead.decrypt(payload[4:16], payload[16:], aad).decode("utf-8")
        except Exception:
            raise CryptoError("DECRYPTION_FAILED") from None

    def digest(self, value: str) -> str:
        if not isinstance(value, str):
            raise CryptoError("INVALID_DIGEST_INPUT")
        try:
            return hmac.new(self._digest_key, value.encode("utf-8"), hashlib.sha256).hexdigest()
        except Exception:
            raise CryptoError("DIGEST_FAILED") from None
