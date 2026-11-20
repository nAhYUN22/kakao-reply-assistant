"""Metadata-only SQLite journal. Message and candidate bodies never enter SQL."""
from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3


class Journal:
    def __init__(self, path: str = ":memory:"):
        self.lock_file = None
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.lock_file = open(path + ".lock", "a+")
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.lock_file.close()
                self.lock_file = None
                raise RuntimeError("DATABASE_ALREADY_IN_USE") from None
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
            INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(digest TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS attempts(job_id TEXT PRIMARY KEY, at TEXT NOT NULL, session_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runtime(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        if self.db.execute("SELECT version FROM schema_version").fetchone()[0] != 1:
            self.close()
            raise RuntimeError("UNSUPPORTED_DATABASE_VERSION")

    def close(self):
        self.db.close()
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None

    def accept_event(self, event_id: str) -> bool:
        # IDs from the simulator are untrusted strings, so do not persist them raw.
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
        try:
            with self.db:
                self.db.execute("INSERT INTO attempts VALUES(?, ?, ?)", (job["job_id"], at, session_id))
                self.db.execute("INSERT OR REPLACE INTO jobs VALUES(?, ?)", (job["job_id"], json.dumps(job)))
            return True
        except sqlite3.IntegrityError:
            return False

    def attempts(self):
        return list(self.db.execute("SELECT job_id, at, session_id FROM attempts"))
