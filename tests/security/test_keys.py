import base64
import fcntl
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from kakaoreply.keys import EphemeralKeyProvider, KeyStoreError, MacOSKeychainProvider


class FakeBackend:
    def __init__(self):
        self.items = {}
        self.reads = 0
        self.writes = 0
        self.read_error = None
        self.write_error = None
        self.replace_on_write = None

    def get_password(self, service, key_id):
        self.reads += 1
        if self.read_error:
            raise self.read_error
        return self.items.get((service, key_id))

    def set_password(self, service, key_id, value):
        self.writes += 1
        if self.write_error:
            raise self.write_error
        self.items[(service, key_id)] = self.replace_on_write or value


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr("kakaoreply.keys.platform.system", lambda: "Darwin")
    return MacOSKeychainProvider(backend=FakeBackend(), lock_path=tmp_path / "provision.lock")


def test_constructor_has_no_keychain_side_effects(provider):
    assert provider._backend.reads == provider._backend.writes == 0


def test_ephemeral_keys_require_explicit_provision_and_do_not_survive_new_provider():
    provider = EphemeralKeyProvider()
    with pytest.raises(KeyStoreError, match="^KEY_NOT_FOUND$"):
        provider.get_key("synthetic-key")
    key = provider.provision("synthetic-key")
    assert len(key) == 32
    assert provider.get_key("synthetic-key") == key
    assert provider.provision("synthetic-key") == key
    with pytest.raises(KeyStoreError, match="^KEY_NOT_FOUND$"):
        EphemeralKeyProvider().get_key("synthetic-key")
    assert repr(key) not in repr(provider)


def test_missing_key_does_not_generate_or_write(provider):
    with pytest.raises(KeyStoreError, match="^KEY_NOT_FOUND$"):
        provider.get_key("synthetic-key")
    assert provider._backend.writes == 0


def test_explicit_provision_readback_and_existing_key_preservation(provider):
    key = provider.provision("synthetic-key")
    assert len(key) == 32
    assert provider._backend.writes == 1
    assert provider.get_key("synthetic-key") == key
    assert provider.provision("synthetic-key") == key
    assert provider._backend.writes == 1
    assert os.stat(provider._lock_path).st_mode & 0o777 == 0o600


def test_parallel_provisioners_keep_the_same_key(provider):
    second = MacOSKeychainProvider(backend=provider._backend, lock_path=provider._lock_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: item.provision("synthetic-key"), [provider, second]))
    assert results[0] == results[1]
    assert provider._backend.writes == 1


def test_external_provision_lock_fails_before_keychain_access(provider):
    with provider._lock_path.open("w") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(KeyStoreError, match="^KEY_PROVISION_LOCK_UNAVAILABLE$"):
            provider.provision("synthetic-key")
    assert provider._backend.reads == provider._backend.writes == 0


@pytest.mark.parametrize("invalid", ["not base64", "", "한글", base64.b64encode(b"too short").decode(), 123])
def test_corrupt_key_never_replaced(provider, invalid):
    provider._backend.items[(provider.SERVICE, "synthetic-key")] = invalid
    with pytest.raises(KeyStoreError, match="^KEYCHAIN_INVALID_KEY$"):
        provider.get_key("synthetic-key")
    with pytest.raises(KeyStoreError, match="^KEYCHAIN_INVALID_KEY$"):
        provider.provision("synthetic-key")
    assert provider._backend.writes == 0


def test_locked_or_failed_backend_never_falls_back_and_redacts_error(provider):
    provider._backend.read_error = RuntimeError("SYNTHETIC_PRIVATE_BACKEND_DETAIL")
    for operation in (provider.get_key, provider.provision):
        with pytest.raises(KeyStoreError, match="^KEYCHAIN_ACCESS_FAILED$") as error:
            operation("synthetic-key")
        assert error.value.__suppress_context__
        assert "SYNTHETIC_PRIVATE_BACKEND_DETAIL" not in str(error.value)
    assert provider._backend.writes == 0


def test_write_error_and_readback_mismatch_are_fatal(provider):
    provider._backend.write_error = RuntimeError("SYNTHETIC_PRIVATE_BACKEND_DETAIL")
    with pytest.raises(KeyStoreError, match="^KEYCHAIN_WRITE_FAILED$"):
        provider.provision("synthetic-key")
    provider._backend.write_error = None
    provider._backend.replace_on_write = base64.b64encode(os.urandom(32)).decode()
    with pytest.raises(KeyStoreError, match="^KEYCHAIN_VERIFICATION_FAILED$"):
        provider.provision("synthetic-key")


def test_unsupported_os_never_constructs_a_native_backend(monkeypatch):
    monkeypatch.setattr("kakaoreply.keys.platform.system", lambda: "Linux")
    with pytest.raises(KeyStoreError, match="^KEYCHAIN_UNSUPPORTED_PLATFORM$"):
        MacOSKeychainProvider()


def test_selects_explicit_macos_backend_without_global_keyring_fallback(monkeypatch):
    import keyring
    import keyring.backends.macOS
    fake = FakeBackend()
    monkeypatch.setattr("kakaoreply.keys.platform.system", lambda: "Darwin")
    monkeypatch.setattr(keyring.backends.macOS, "Keyring", lambda: fake)
    monkeypatch.setattr(keyring, "get_keyring", lambda: pytest.fail("automatic backend selection forbidden"))
    provider = MacOSKeychainProvider()
    assert provider._backend is fake
    assert fake.reads == fake.writes == 0


@pytest.mark.parametrize("bad_id", ["", "../secret", "synthetic\nsecret", "x" * 101, None])
def test_invalid_reference_rejected_before_backend(provider, bad_id):
    with pytest.raises(KeyStoreError, match="^INVALID_KEY_REFERENCE$"):
        provider.get_key(bad_id)
    assert provider._backend.reads == provider._backend.writes == 0
