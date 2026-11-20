"""Explicit, one-shot CLI catalog + MCP read diagnostics for the local UI.

Calling verify means the API has already obtained the user's confirmation that
its selected conversation is 1:1. Results prove neither author identity nor send
readiness. Catalogs are bounded UI observations, not exhaustive account indexes.
Explicit named replies use a separate exact-window single-press helper.
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
import unicodedata

from ..domain import SUFFIX
from .reply_snapshot import CONTEXT_LIMIT, ReplySnapshot, make_context, matches_new_echo, require_recent
from .scoped_dispatch import prepare_scoped_press
from .mcp_client import McpReadClient
from .observation import BindingVerifier, ReadError, SnapshotScanner, _catalog, parse_snapshot

CATALOG_LIMIT = 1000
MAX_CATALOG_BYTES = 512_000
MAX_DIRECT_READ_BYTES = 128_000
DEFAULT_MCP_TIMEOUT_SECONDS = 12
DEFAULT_CATALOG_TIMEOUT_SECONDS = 30
_LOCK_PATH = Path('/tmp') / f'kakaoreply-kakao-ui-{os.getuid()}.lock'
_SAFE_ERRORS = frozenset({
    'BINARY_UNAVAILABLE', 'PROBE_BUSY', 'UI_LOCK_UNAVAILABLE', 'INVALID_CONFIGURATION',
    'CATALOG_FAILED', 'CATALOG_TIMEOUT', 'CATALOG_TOO_LARGE', 'CATALOG_LIMIT_REACHED',
    'INVALID_CATALOG', 'INVALID_PAYLOAD', 'AMBIGUOUS_TARGET', 'BINDING_CHANGED',
    'BINDING_REQUIRES_CONFIRMATION', 'SELECTION_EXPIRED', 'READ_FAILED',
    'READ_CAPABILITY_MISSING', 'UNSUPPORTED_READ_SCHEMA', 'UNSUPPORTED_TOOL_PAGINATION',
    'MCP_CONNECTION_FAILED', 'MCP_READ_FAILED', 'CONFLICTING_PAYLOAD', 'PAYLOAD_TOO_LARGE',
    'INVALID_TIMESTAMP', 'NOT_CONNECTED', 'PROBE_FAILED',
    'INVALID_CHAT_NAME', 'TITLE_MISMATCH', 'DIRECT_READ_TIMEOUT',
    'DIRECT_READ_FAILED', 'DIRECT_READ_TOO_LARGE', 'EMPTY_CONTEXT', 'LAST_NOT_PARTNER',
    'AMBIGUOUS_AUTHOR', 'UNSUPPORTED_CONTENT', 'STALE_INPUT',
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


def _search_variants(title: str) -> set[str]:
    # A conservative superset of kmsg v1.260921.0 search-token matching.
    # NFKD/casefold also catches width, accent and case collisions; excessive
    # ambiguity is safer than treating this partial UI catalog as identity proof.
    def token(value):
        return ''.join(character for character in unicodedata.normalize('NFKD', value).casefold()
                       if not character.isspace()
                       and unicodedata.category(character)[0] not in {'P', 'S', 'M'}
                       and unicodedata.category(character) != 'Cf')
    normalized = token(title)
    variants = {normalized} if normalized else set()
    for suffix in ('선생님', '님', '씨'):
        normalized_suffix = token(suffix)
        if normalized.endswith(normalized_suffix) and len(normalized) > len(normalized_suffix):
            variants.add(normalized[:-len(normalized_suffix)])
    return variants


def _require_unambiguous_search(binding, catalog):
    selected = _search_variants(binding.title)
    if not selected:
        raise ReadError('AMBIGUOUS_TARGET')
    for chat_id, title in _catalog(catalog):
        if chat_id == binding.chat_id:
            continue
        if any(left in right or right in left
               for left in selected for right in _search_variants(title)):
            raise ReadError('AMBIGUOUS_TARGET')


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
                 timeout_seconds: float | None = None,
                 catalog_timeout_seconds: float | None = None, clock=None, sleep=None):
        # Large AX catalog scans can take longer than a single bounded MCP read.
        # Preserve explicit timeout_seconds overrides (including synthetic tests)
        # for both operations unless a separate catalog override is supplied.
        read_timeout = DEFAULT_MCP_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        catalog_timeout = (DEFAULT_CATALOG_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds)
        if catalog_timeout_seconds is not None:
            catalog_timeout = catalog_timeout_seconds
        if (not math.isfinite(poll_seconds) or not 0 <= poll_seconds <= 5
                or not math.isfinite(read_timeout) or not 0 < read_timeout <= 30
                or not math.isfinite(catalog_timeout) or not 0 < catalog_timeout <= 60):
            raise ReadError('INVALID_CONFIGURATION')
        self._executable = executable
        self._poll_seconds = poll_seconds
        self._timeout = read_timeout
        self._catalog_timeout = catalog_timeout
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

    async def _run_cli_json(self, binary: str, arguments: tuple[str, ...], *,
                            timeout: float, max_bytes: int, operation: str):
        """Internal bounded runner; public methods supply fixed command shapes."""
        process = None
        try:
            async with asyncio.timeout(timeout):
                process = await asyncio.create_subprocess_exec(
                    binary, *arguments,
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
                    env={**os.environ, 'KMSG_TRACE_DEFAULT': 'false', 'KMSG_DEFAULT_DEEP_RECOVERY': 'false'})
                chunks = bytearray()
                while True:
                    chunk = await process.stdout.read(min(65536, max_bytes + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if len(chunks) > max_bytes:
                        raise ReadError(f'{operation}_TOO_LARGE')
                if await process.wait() != 0:
                    raise ReadError(f'{operation}_FAILED')
            try:
                return json.loads(chunks, object_pairs_hook=_json_pairs)
            except Exception:
                raise ReadError(f'{operation}_FAILED') from None
        except TimeoutError:
            raise ReadError(f'{operation}_TIMEOUT') from None
        except asyncio.CancelledError:
            raise
        except ReadError:
            raise
        except Exception:
            raise ReadError(f'{operation}_FAILED') from None
        finally:
            if process is not None:
                await _stop_process(process)

    async def _read_catalog(self, binary: str) -> dict:
        raw = await self._run_cli_json(binary, ('chats', '--json', '--limit', str(CATALOG_LIMIT)),
                                       timeout=self._catalog_timeout, max_bytes=MAX_CATALOG_BYTES, operation='CATALOG')
        rows = _catalog(raw)
        if len(rows) >= CATALOG_LIMIT:
            raise ReadError('CATALOG_LIMIT_REACHED')
        # Drop previews and all unknown fields before caching or returning.
        return {'count': len(rows), 'chats': [{'chat_id': chat_id, 'title': title} for chat_id, title in rows]}

    @staticmethod
    def _target(name):
        if (not isinstance(name, str) or not 1 <= len(name) <= 500
                or any(unicodedata.category(c).startswith('C') or unicodedata.category(c) in {'Zl', 'Zp'}
                       for c in name)):
            raise ReadError('INVALID_CHAT_NAME')
        target = name.strip()
        if not target or target.startswith('-'):
            raise ReadError('INVALID_CHAT_NAME')
        return target

    async def _read_named(self, binary, target, limit, *selector):
        raw = await self._run_cli_json(binary, ('read', '--json', '--limit', str(limit), *(selector or (target,))),
                                      timeout=self._timeout, max_bytes=MAX_DIRECT_READ_BYTES,
                                      operation='DIRECT_READ')
        if not isinstance(raw, dict):
            raise ReadError('DIRECT_READ_FAILED')
        if raw.get('chat') != target:
            raise ReadError('TITLE_MISMATCH')
        if 'ok' in raw or type(raw.get('count')) is not int or not 0 <= raw['count'] <= limit:
            raise ReadError('DIRECT_READ_FAILED')
        try:
            return parse_snapshot({'ok': True, **raw})
        except Exception:
            raise ReadError('DIRECT_READ_FAILED') from None

    async def direct_read(self, name: str) -> dict:
        """One explicit foreground CLI read; an exact title does not prove identity."""
        try:
            target = self._target(name)
            with _ui_lock():
                snapshot = await self._read_named(self._binary(), target, 3)
                return {'status': 'READ', 'count': len(snapshot.rows)}
        except Exception as error:
            raise _safe_error(error) from None

    async def reply_context(self, name: str) -> ReplySnapshot:
        """API caller confirms the title and partner display name in a 1:1 room."""
        try:
            target = self._target(name)
            with _ui_lock():
                snapshot = await self._read_named(self._binary(), target, CONTEXT_LIMIT)
                return make_context(snapshot)
        except Exception as error:
            raise _safe_error(error) from None

    async def send_if_current(self, name, expected_snapshot, body, before_attempt):
        target = self._target(name)
        if (not isinstance(body, str) or not body.endswith('\n' + SUFFIX)
                or body.count(SUFFIX) != 1 or not body[:-len(SUFFIX)].strip() or len(body) > 240):
            raise ReadError('UNSUPPORTED_CONTENT')
        if not isinstance(expected_snapshot, ReplySnapshot):
            raise ReadError('CONTEXT_CHANGED')
        with _ui_lock():
            binary = self._binary()
            catalog = await self._read_catalog(binary)
            ids = [identity for identity, title in _catalog(catalog) if title == target]
            if len(ids) != 1:
                raise ReadError('AMBIGUOUS_TARGET')
            binding = self._verifier.bind(catalog, ids[0], one_to_one_confirmed=True)
            _require_unambiguous_search(binding, catalog)
            # --chat-id can still fall back to fuzzy name resolution in kmsg.
            # Require both exact returned title and exact timestamped transcript.
            selector = ('--chat-id', binding.chat_id)
            current = await self._read_named(binary, target, CONTEXT_LIMIT, '--keep-window', *selector)
            if make_context(current) != expected_snapshot:
                raise ReadError('CONTEXT_CHANGED')
            require_recent(current, self._clock())
            async with prepare_scoped_press(target, body, self._timeout, _stop_process) as submit:
                current = await self._read_named(binary, target, CONTEXT_LIMIT, '--background-safe', *selector)
                if make_context(current) != expected_snapshot:
                    raise ReadError('CONTEXT_CHANGED')
                require_recent(current, self._clock())
                before_attempt()
                await submit()
                echo = await self._read_named(binary, target, CONTEXT_LIMIT, '--background-safe', *selector)
                if not matches_new_echo(current, echo, body):
                    raise ReadError('DELIVERY_UNKNOWN')

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

    async def verify(self, id: str, *, allow_open_window: bool = False) -> dict:
        """API confirms 1:1 and separately opts in to foreground UI automation.

        kmsg foreground may open/activate/search/close windows and retry recovery.
        We reject known near-name collisions and exact-title mismatches, but the
        catalog is not an exhaustive list and upstream does not prove identity.
        """
        try:
            if type(allow_open_window) is not bool:
                raise ReadError('INVALID_CONFIGURATION')
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
                    # Both upstream background and foreground resolution use
                    # fuzzy name matching after resolving the local chat ID.
                    _require_unambiguous_search(binding, fresh_catalog)
                    baseline = await client.read_snapshot(binding, allow_open_window=allow_open_window)
                    first = scanner.scan(baseline, observed_at=self._clock())
                    if first.status != 'BASELINE':
                        return {'baseline_count': 0, 'new_count': 0, 'status': first.status}
                    baseline_count = len(baseline.rows)
                    await self._sleep(self._poll_seconds)
                    fresh_catalog = await self._read_catalog(binary)
                    verifier.verify(binding, fresh_catalog)
                    _require_unambiguous_search(binding, fresh_catalog)
                    current = await client.read_snapshot(binding, allow_open_window=allow_open_window)
                    observation = scanner.scan(current, observed_at=self._clock())
                    return {'baseline_count': baseline_count, 'new_count': len(observation.events), 'status': observation.status}
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise _safe_error(error) from None
