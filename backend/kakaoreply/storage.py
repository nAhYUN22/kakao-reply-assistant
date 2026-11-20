"""Transactional metadata journal with optional authenticated body storage."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .crypto import DataCipher


class StorageError(ValueError):
    """Public errors contain only stable codes, never database values or keys."""


class Journal:
    def __init__(self, path: str = ":memory:", *, cipher: DataCipher | None = None,
                 key_check: Callable[[], None] | None = None):
        self.lock_file = None
        self.db = None
        self.cipher = cipher
        self.key_check = key_check
        if path != ":memory:":
            path = str(Path(path).resolve())
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.lock_file = open(path + ".lock", "a+")
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.lock_file.close()
                self.lock_file = None
                raise RuntimeError("DATABASE_ALREADY_IN_USE") from None
        try:
            self.db = sqlite3.connect(path, check_same_thread=False)
            self.db.execute("PRAGMA journal_mode=WAL")
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                self._migrate()
                self._bind_key()
        except BaseException:
            self.close()
            raise

    @property
    def encrypted(self) -> bool:
        return self.cipher is not None

    def _migrate(self):
        exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
        if not exists:
            self.db.execute("CREATE TABLE schema_version(version INTEGER NOT NULL)")
            self.db.execute("INSERT INTO schema_version VALUES(1)")
            self.db.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY, metadata TEXT NOT NULL)")
            self.db.execute("CREATE TABLE events(digest TEXT PRIMARY KEY)")
            self.db.execute("CREATE TABLE attempts(job_id TEXT PRIMARY KEY, at TEXT NOT NULL, session_id TEXT NOT NULL)")
            self.db.execute("CREATE TABLE runtime(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        versions = self.db.execute("SELECT version FROM schema_version").fetchall()
        if len(versions) != 1 or versions[0][0] not in (1, 2):
            raise StorageError("UNSUPPORTED_DATABASE_VERSION")
        if versions[0][0] == 1:
            self.db.execute("CREATE TABLE encryption(key_id TEXT NOT NULL, verifier BLOB NOT NULL)")
            self.db.execute("CREATE TABLE sensitive(kind TEXT NOT NULL, id TEXT NOT NULL, ciphertext BLOB NOT NULL, expires_at TEXT NOT NULL, PRIMARY KEY(kind,id))")
            self.db.execute("UPDATE schema_version SET version=2")

    def ensure_key(self):
        if self.key_check is not None:
            try:
                self.key_check()
            except Exception:
                raise StorageError("KEY_UNAVAILABLE") from None

    def _bind_key(self):
        rows = self.db.execute("SELECT key_id,verifier FROM encryption").fetchall()
        if len(rows) > 1:
            raise StorageError("INVALID_ENCRYPTION_METADATA")
        if rows:
            if self.cipher is None or rows[0][0] != self.cipher.key_id:
                raise StorageError("ENCRYPTION_KEY_REQUIRED")
            self.ensure_key()
            try:
                verified = self.cipher.decrypt("encryption:v2", "verifier", rows[0][1])
            except Exception:
                raise StorageError("KEY_OR_DATABASE_INVALID") from None
            if verified != "KakaoReply encrypted store v2":
                raise StorageError("KEY_OR_DATABASE_INVALID")
        elif self.cipher is not None:
            if self.db.execute("SELECT 1 FROM sensitive LIMIT 1").fetchone():
                raise StorageError("ENCRYPTION_METADATA_MISSING")
            self.ensure_key()
            try:
                verifier = self.cipher.encrypt("encryption:v2", "verifier", "KakaoReply encrypted store v2")
            except Exception:
                raise StorageError("ENCRYPTION_FAILED") from None
            self.db.execute("INSERT INTO encryption VALUES(?,?)", (self.cipher.key_id, verifier))
        elif self.db.execute("SELECT 1 FROM sensitive LIMIT 1").fetchone():
            raise StorageError("ENCRYPTION_KEY_REQUIRED")

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None

    def accept_event(self, event_id: str) -> bool:
        # Preserve v1 event identity across migration; no raw text/ID is stored.
        digest = hashlib.sha256(event_id.encode()).hexdigest()
        with self.db:
            cursor = self.db.execute("INSERT OR IGNORE INTO events VALUES(?)", (digest,))
        return cursor.rowcount == 1

    def save_job(self, job: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO jobs VALUES(?, ?)",
                            (job["job_id"], json.dumps(job)))

    def jobs(self) -> dict[str, dict]:
        return {key: json.loads(value) for key, value in self.db.execute("SELECT id, metadata FROM jobs")}

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM runtime WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO runtime VALUES(?, ?)", (key, json.dumps(value)))

    def claim(self, job: dict, at: str, session_id: str) -> bool:
        self.ensure_key()
        try:
            with self.db:
                self.db.execute("INSERT INTO attempts VALUES(?, ?, ?)", (job["job_id"], at, session_id))
                self.db.execute("INSERT OR REPLACE INTO jobs VALUES(?, ?)", (job["job_id"], json.dumps(job)))
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.Error:
            raise StorageError("OUTBOX_WRITE_FAILED") from None

    def attempts(self):
        return list(self.db.execute("SELECT job_id, at, session_id FROM attempts"))

    @staticmethod
    def _utc(now: datetime) -> str:
        if now.tzinfo is None:
            raise StorageError("UTC_TIMESTAMP_REQUIRED")
        return now.astimezone(timezone.utc).isoformat()

    def save_body(self, kind: str, row_id: str, text: str, now: datetime, days: int = 7):
        if self.cipher is None:
            raise StorageError("ENCRYPTION_REQUIRED")
        if kind not in {"reply", "message", "binding"} or not row_id or not 1 <= days <= 365:
            raise StorageError("INVALID_SENSITIVE_RECORD")
        self.ensure_key()
        expires = self._utc(now + timedelta(days=days))
        try:
            ciphertext = self.cipher.encrypt("sensitive:v2:" + kind, row_id, text)
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO sensitive VALUES(?,?,?,?)", (kind, row_id, ciphertext, expires))
        except Exception:
            raise StorageError("ENCRYPTED_WRITE_FAILED") from None

    def load_body(self, kind: str, row_id: str, now: datetime) -> str | None:
        self.ensure_key()
        row = self.db.execute("SELECT ciphertext,expires_at FROM sensitive WHERE kind=? AND id=?", (kind, row_id)).fetchone()
        if row is None:
            return None
        if self.cipher is None:
            raise StorageError("ENCRYPTION_REQUIRED")
        if row[1] <= self._utc(now):
            self.delete_body(kind, row_id)
            return None
        try:
            return self.cipher.decrypt("sensitive:v2:" + kind, row_id, row[0])
        except Exception:
            raise StorageError("ENCRYPTED_READ_FAILED") from None

    def delete_body(self, kind: str, row_id: str):
        with self.db:
            self.db.execute("DELETE FROM sensitive WHERE kind=? AND id=?", (kind, row_id))

    def purge_expired(self, now: datetime) -> int:
        with self.db:
            cursor = self.db.execute("DELETE FROM sensitive WHERE expires_at<=?", (self._utc(now),))
        return cursor.rowcount
