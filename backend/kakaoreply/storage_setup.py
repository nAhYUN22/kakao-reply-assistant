"""Explicit Keychain setup and fail-closed journal construction."""
from __future__ import annotations

import argparse
import hmac
import os

from .crypto import DataCipher
from .keys import KeyProvider, MacOSKeychainProvider
from .storage import Journal, StorageError


def open_journal(path: str, *, mode: str = "metadata_only", key_id: str | None = None,
                 provider: KeyProvider | None = None) -> Journal:
    if mode == "metadata_only":
        if key_id is not None or provider is not None:
            raise StorageError("INCONSISTENT_STORAGE_SETTINGS")
        return Journal(path)
    if mode != "keychain" or not key_id:
        raise StorageError("INVALID_STORAGE_SETTINGS")
    provider = provider or MacOSKeychainProvider()
    try:
        original_key = provider.get_key(key_id)
        cipher = DataCipher(original_key, key_id)
    except Exception:
        raise StorageError("KEY_UNAVAILABLE") from None

    def check_key():
        if not hmac.compare_digest(provider.get_key(key_id), original_key):
            raise StorageError("KEY_CHANGED")

    return Journal(path, cipher=cipher, key_check=check_key)


def journal_from_environment(path: str) -> Journal:
    return open_journal(path, mode=os.getenv("KAKAOREPLY_KEY_STORE", "metadata_only"),
                        key_id=os.getenv("KAKAOREPLY_KEY_ID"))


def main() -> int:
    parser = argparse.ArgumentParser(description="KakaoReply 전용 암호화 키를 macOS Keychain에 생성합니다. 키 값은 출력하지 않습니다.")
    parser.add_argument("command", choices=["init-key"])
    parser.add_argument("--key-id", required=True, help="개인정보가 없는 키 참조 이름")
    args = parser.parse_args()
    try:
        MacOSKeychainProvider().provision(args.key_id)
    except Exception:
        print("키 준비에 실패했습니다. Keychain 접근 상태를 확인하세요. 평문 저장으로 전환하지 않았습니다.")
        return 1
    print("Keychain 키 준비를 확인했습니다. 키 값은 출력하지 않습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
