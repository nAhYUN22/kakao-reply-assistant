import hashlib
import hmac
import os

import pytest

from kakaoreply.crypto import CryptoError, DataCipher


@pytest.fixture
def key():
    return os.urandom(32)


def test_unicode_round_trip_uses_distinct_nonce_and_hides_body(key):
    cipher = DataCipher(key, "synthetic-key-1")
    text = "합성 문장과 결합 문자 e\u0301 및 이모지 🫶"
    first = cipher.encrypt("job_bodies", "synthetic-row", text)
    second = cipher.encrypt("job_bodies", "synthetic-row", text)
    assert first != second
    assert first[4:16] != second[4:16]
    assert text.encode() not in first
    assert key not in first
    assert cipher.decrypt("job_bodies", "synthetic-row", first) == text


@pytest.mark.parametrize("change", ["ciphertext", "nonce", "version", "truncated", "table", "row", "key", "key_id", "aad_version"])
def test_tampering_and_cross_row_replay_fail_closed(key, change):
    cipher = DataCipher(key, "synthetic-key-1")
    payload = cipher.encrypt("job_bodies", "row-1", "SYNTHETIC_PRIVATE_BODY")
    table, row = "job_bodies", "row-1"
    if change == "ciphertext":
        payload = payload[:-1] + bytes([payload[-1] ^ 1])
    elif change == "nonce":
        payload = payload[:4] + bytes([payload[4] ^ 1]) + payload[5:]
    elif change == "version":
        payload = b"KRE2" + payload[4:]
    elif change == "truncated":
        payload = payload[:20]
    elif change == "table":
        table = "other_table"
    elif change == "row":
        row = "row-2"
    elif change == "key":
        cipher = DataCipher(os.urandom(32), "synthetic-key-1")
    elif change == "key_id":
        cipher = DataCipher(key, "synthetic-key-2")
    else:
        class NewVersionCipher(DataCipher):
            _VERSION = 2
        cipher = NewVersionCipher(key, "synthetic-key-1")
    with pytest.raises(CryptoError) as error:
        cipher.decrypt(table, row, payload)
    assert "SYNTHETIC_PRIVATE_BODY" not in str(error.value)
    assert repr(key) not in repr(error.value)


def test_hmac_is_stable_keyed_and_separate_from_encryption_key(key):
    cipher = DataCipher(key, "synthetic-key")
    message = "synthetic-event-1"
    digest = cipher.digest(message)
    assert len(digest) == 64
    assert digest == DataCipher(key, "synthetic-key").digest(message)
    assert digest != DataCipher(os.urandom(32), "synthetic-key").digest(message)
    assert digest != hashlib.sha256(message.encode()).hexdigest()
    assert digest != hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    assert digest != cipher.digest(message + "2")


def test_cipher_repr_has_no_key_or_reference(key):
    cipher = DataCipher(key, "SYNTHETIC_REF")
    assert repr(key) not in repr(cipher)
    assert key.hex() not in repr(cipher)
    assert "SYNTHETIC_REF" not in repr(cipher)


@pytest.mark.parametrize("key", [b"", b"a" * 16, b"a" * 31, b"a" * 33, "secret", bytearray(32)])
def test_rejects_invalid_keys_without_echo(key):
    with pytest.raises(CryptoError, match="^INVALID_ENCRYPTION_KEY$"):
        DataCipher(key, "synthetic-key")


def test_empty_plaintext_is_authenticated(key):
    cipher = DataCipher(key, "synthetic-key")
    payload = cipher.encrypt("job_bodies", "row-1", "")
    assert len(payload) == 32
    assert cipher.decrypt("job_bodies", "row-1", payload) == ""


def test_invalid_encoding_and_context_are_sanitized(key):
    cipher = DataCipher(key, "synthetic-key")
    with pytest.raises(CryptoError, match="^ENCRYPTION_FAILED$"):
        cipher.encrypt("job_bodies", "row-1", "SYNTHETIC_PRIVATE\ud800")
    with pytest.raises(CryptoError, match="^INVALID_ENCRYPTION_CONTEXT$"):
        cipher.encrypt("", "row-1", "body")
    with pytest.raises(CryptoError, match="^INVALID_ENCRYPTED_PAYLOAD$"):
        cipher.decrypt("job_bodies", "row-1", "SYNTHETIC_PRIVATE_BODY")
