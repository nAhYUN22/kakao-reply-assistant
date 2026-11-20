"""Explicit, one-shot CLI catalog + MCP read diagnostics for the local UI.

Calling verify means the API has already obtained the user's confirmation that
its selected conversation is 1:1. Results prove neither author identity nor send
readiness. Catalogs are bounded UI observations, not exhaustive account indexes.
No background tasks, message storage, general tool invocation, or send methods.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import signal
import stat
import time

from .mcp_client import McpReadClient
from .observation import BindingVerifier, ReadError, SnapshotScanner, _catalog

CATALOG_LIMIT = 1000
MAX_CATALOG_BYTES = 512_000
_LOCK_PATH = Path('/tmp') / f'kakaoreply-kakao-ui-{os.getuid()}.lock'
_SAFE_ERRORS = frozenset({
    'BINARY_UNAVAILABLE', 'PROBE_BUSY', 'UI_LOCK_UNAVAILABLE', 'INVALID_CONFIGURATION',
    'CATALOG_FAILED', 'CATALOG_TIMEOUT', 'CATALOG_TOO_LARGE', 'CATALOG_LIMIT_REACHED',
    'INVALID_CATALOG', 'INVALID_PAYLOAD', 'AMBIGUOUS_TARGET', 'BINDING_CHANGED',
    'BINDING_REQUIRES_CONFIRMATION', 'SELECTION_EXPIRED', 'READ_FAILED',
    'READ_CAPABILITY_MISSING', 'UNSUPPORTED_READ_SCHEMA', 'UNSUPPORTED_TOOL_PAGINATION',
    'MCP_CONNECTION_FAILED', 'MCP_READ_FAILED', 'CONFLICTING_PAYLOAD', 'PAYLOAD_TOO_LARGE',
    'INVALID_TIMESTAMP', 'NOT_CONNECTED', 'PROBE_FAILED',
})


def _safe_error(error: Exception) -> ReadError:
    code = str(error) if isinstance(error, ReadError) else ''
    return ReadError(code if code in _SAFE_ERRORS else 'PROBE_FAILED')


@contextmanager
def _ui_lock():
    """Same fixed per-user lock across Probe instances and SQLite locations.

    Other KakaoReply UI operations must acquire this lock when added. It cannot
    coordinate unrelated applications or a user's own kmsg CLI processes.
    """
    descriptor = None
    acquired = False
    try:
        try:
            descriptor = os.open(_LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
                raise ReadError('UI_LOCK_UNAVAILABLE')
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            raise ReadError('PROBE_BUSY') from None
        except OSError:
            raise ReadError('UI_LOCK_UNAVAILABLE') from None
        yield
    finally:
        if descriptor is not None:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReadError('INVALID_CATALOG')
        result[key] = value
    return result


async def _stop_process(process):
    # Catalog can open UI; cancellation must not leave its subprocess running.
    async def discard_stdout():
        while await process.stdout.read(65536):
            pass
    drain = asyncio.create_task(discard_stdout())
    try:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            async with asyncio.timeout(.5):
                await process.wait()
        except TimeoutError:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        await drain
    finally:
        if not drain.done():
            drain.cancel()
            await asyncio.gather(drain, return_exceptions=True)


class Probe:
    def __init__(self, executable: str | None = None, *, poll_seconds: float = 3,
                 timeout_seconds: float = 12, clock=None, sleep=None):
        if (not math.isfinite(poll_seconds) or not 0 <= poll_seconds <= 5
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30):
            raise ReadError('INVALID_CONFIGURATION')
        self._executable = executable
        self._poll_seconds = poll_seconds
        self._timeout = timeout_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or asyncio.sleep
        self._choices: dict[str, str] = {}
        self._verifier = BindingVerifier()
        self._fingerprint: str | None = None
        self._expires = 0.0

    def _binary(self) -> str:
        candidate = self._executable if self._executable is not None else shutil.which('kmsg')
        if not candidate:
            raise ReadError('BINARY_UNAVAILABLE')
        path = Path(candidate)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ReadError('BINARY_UNAVAILABLE')
        return str(path)

    def installed(self) -> bool:
        """Only inspect executable availability; never start kmsg or read chats."""
        try:
            self._binary()
            return True
        except (ReadError, OSError):
            return False

    async def _read_catalog(self, binary: str) -> dict:
        process = None
        try:
            async with asyncio.timeout(self._timeout):
                process = await asyncio.create_subprocess_exec(
                    binary, 'chats', '--json', '--limit', str(CATALOG_LIMIT),
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
                    env={**os.environ, 'KMSG_TRACE_DEFAULT': 'false', 'KMSG_DEFAULT_DEEP_RECOVERY': 'false'})
                chunks = bytearray()
                while True:
                    chunk = await process.stdout.read(min(65536, MAX_CATALOG_BYTES + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if len(chunks) > MAX_CATALOG_BYTES:
                        raise ReadError('CATALOG_TOO_LARGE')
                if await process.wait() != 0:
                    raise ReadError('CATALOG_FAILED')
            raw = json.loads(chunks, object_pairs_hook=_json_pairs)
            rows = _catalog(raw)
            if len(rows) >= CATALOG_LIMIT:
                raise ReadError('CATALOG_LIMIT_REACHED')
            # Drop previews and all unknown fields before caching or returning.
            return {'count': len(rows), 'chats': [{'chat_id': chat_id, 'title': title} for chat_id, title in rows]}
        except TimeoutError:
            raise ReadError('CATALOG_TIMEOUT') from None
        except asyncio.CancelledError:
            raise
        except ReadError:
            raise
        except Exception:
            raise ReadError('CATALOG_FAILED') from None
        finally:
            if process is not None:
                await _stop_process(process)

    async def catalog(self) -> dict:
        try:
            with _ui_lock():
                self._choices, self._fingerprint, self._expires = {}, None, 0
                raw = await self._read_catalog(self._binary())
                choices = []
                for row in raw['chats']:
                    opaque_id = secrets.token_urlsafe(24)
                    self._choices[opaque_id] = row['chat_id']
                    choices.append({'id': opaque_id, 'title': row['title']})
                # Keep only a keyed catalog fingerprint and opaque ID mapping.
                # Display names/previews never become a persistent server cache.
                self._fingerprint = self._verifier._digest(_catalog(raw))
                self._expires = time.monotonic() + 300
                return {'choices': choices}
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise _safe_error(error) from None

    async def verify(self, id: str) -> dict:
        """API must enforce selected 1:1 confirmation before calling this method."""
        try:
            with _ui_lock():
                if (not isinstance(id, str) or id not in self._choices
                        or self._fingerprint is None or time.monotonic() > self._expires):
                    if time.monotonic() > self._expires:
                        self._choices, self._fingerprint = {}, None
                    raise ReadError('SELECTION_EXPIRED')
                binary = self._binary()
                verifier = self._verifier
                client = McpReadClient.for_kmsg(binary, timeout_seconds=self._timeout)
                async with client.connect():
                    # Explicit CLI catalog, never a hidden MCP fallback. Both
                    # snapshots use one initialized MCP session and fresh IDs.
                    fresh_catalog = await self._read_catalog(binary)
                    if not hmac.compare_digest(self._fingerprint, verifier._digest(_catalog(fresh_catalog))):
                        raise ReadError('BINDING_CHANGED')
                    binding = verifier.bind(fresh_catalog, self._choices[id], one_to_one_confirmed=True)
                    scanner = SnapshotScanner(binding)
                    verifier.verify(binding, fresh_catalog)
                    baseline = await client.read_snapshot(binding)
                    first = scanner.scan(baseline, observed_at=self._clock())
                    if first.status != 'BASELINE':
                        return {'baseline_count': 0, 'new_count': 0, 'status': first.status}
                    baseline_count = len(baseline.rows)
                    await self._sleep(self._poll_seconds)
                    verifier.verify(binding, await self._read_catalog(binary))
                    current = await client.read_snapshot(binding)
                    observation = scanner.scan(current, observed_at=self._clock())
                    return {'baseline_count': baseline_count, 'new_count': len(observation.events), 'status': observation.status}
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise _safe_error(error) from None
