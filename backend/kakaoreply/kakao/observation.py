"""Conservative, in-memory interpretation of kmsg's non-durable chat identities.

These objects are read evidence, never a SendGate permit. No disk or UI access.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from uuid import uuid4
from zoneinfo import ZoneInfo


class ReadError(Exception):
    """Only application-owned codes are exposed; upstream errors are discarded."""


@dataclass(frozen=True)
class Binding:
    binding_id: str
    chat_id: str = field(repr=False)
    title: str = field(repr=False)
    catalog_digest: str = field(repr=False)
    partner_author: str | None = field(default=None, repr=False)
    owner_author: str | None = field(default=None, repr=False)
    revision: int = 1


def _string(value: object, max_size: int = 10000, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > max_size or (not empty and not value):
        raise ReadError('INVALID_PAYLOAD')
    return value


def _catalog(raw: dict) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, dict) or not isinstance(raw.get('chats'), list):
        raise ReadError('INVALID_CATALOG')
    if len(raw['chats']) > 10000 or type(raw.get('count')) is not int or raw['count'] != len(raw['chats']):
        raise ReadError('INVALID_CATALOG')
    rows = []
    for row in raw['chats']:
        if not isinstance(row, dict):
            raise ReadError('INVALID_CATALOG')
        rows.append((_string(row.get('chat_id'), 200), _string(row.get('title'), 500)))
    if len(set(x[0] for x in rows)) != len(rows):
        raise ReadError('AMBIGUOUS_TARGET')
    return tuple(sorted(rows))


class BindingVerifier:
    """Caller supplies a fresh catalog and user-verified 1:1/author evidence.

    MCP has no catalog tool. This does not run a hidden CLI fallback or treat a
    name match as proof of real account identity. Recreate after process restart.
    """
    def __init__(self):
        self._key = secrets.token_bytes(32)

    def _digest(self, rows: tuple) -> str:
        return hmac.new(self._key, json.dumps(rows, ensure_ascii=False).encode(), hashlib.sha256).hexdigest()

    def bind(self, catalog: dict, selected_id: str, *, one_to_one_confirmed: bool,
             partner_author: str | None = None, owner_author: str | None = None,
             authors_confirmed: bool = False) -> Binding:
        rows = _catalog(catalog)
        matches = [row for row in rows if row[0] == selected_id]
        if one_to_one_confirmed is not True or len(matches) != 1:
            raise ReadError('BINDING_REQUIRES_CONFIRMATION')
        chat_id, title = matches[0]
        if sum(name == title for _, name in rows) != 1:
            raise ReadError('AMBIGUOUS_TARGET')
        if authors_confirmed:
            for value in (partner_author, owner_author):
                if value is not None:
                    _string(value, 500)
            # kmsg's fallback marker cannot prove owner or partner identity.
            if '(me)' in (partner_author, owner_author) or (partner_author and partner_author == owner_author):
                raise ReadError('AMBIGUOUS_AUTHOR')
        else:
            partner_author = owner_author = None
        return Binding(str(uuid4()), chat_id, title, self._digest(rows), partner_author, owner_author)

    def verify(self, binding: Binding, catalog: dict) -> None:
        rows = _catalog(catalog)
        if not hmac.compare_digest(binding.catalog_digest, self._digest(rows)):
            raise ReadError('BINDING_CHANGED')
        if (binding.chat_id, binding.title) not in rows:
            raise ReadError('BINDING_CHANGED')


@dataclass(frozen=True, repr=False)
class Row:
    author: str | None
    body: str
    date: str | None
    time_raw: str | None
    attachments: bool


@dataclass(frozen=True, repr=False)
class Snapshot:
    chat: str
    rows: tuple[Row, ...]
    fetched_at: datetime


def _instant(value: object) -> datetime:
    try:
        result = datetime.fromisoformat(_string(value, 100).replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ReadError('INVALID_TIMESTAMP') from None


def parse_snapshot(raw: dict) -> Snapshot:
    if not isinstance(raw, dict) or raw.get('ok') is not True:
        raise ReadError('READ_FAILED')
    if len(json.dumps(raw, ensure_ascii=False).encode()) > 1_100_000:
        raise ReadError('PAYLOAD_TOO_LARGE')
    messages = raw.get('messages')
    if not isinstance(messages, list) or len(messages) > 100 or type(raw.get('count')) is not int or raw['count'] != len(messages):
        raise ReadError('INVALID_PAYLOAD')
    rows = []
    for message in messages:
        if not isinstance(message, dict):
            raise ReadError('INVALID_PAYLOAD')
        author = message.get('author')
        if author is not None:
            author = _string(author, 500, empty=True) or None
        date, time_raw = message.get('date'), message.get('time_raw')
        for value in (date, time_raw):
            if value is not None:
                _string(value, 100, empty=True)
        attachments = False
        for name in ('has_image', 'has_attachment'):
            value = message.get(name, False)
            if type(value) is not bool:
                raise ReadError('INVALID_PAYLOAD')
            attachments |= value
        for name in ('image_count', 'attachment_count', 'link_count'):
            value = message.get(name, 0)
            if type(value) is not int or not 0 <= value <= 10000:
                raise ReadError('INVALID_PAYLOAD')
            attachments |= value > 0
        rows.append(Row(author, _string(message.get('body'), empty=True), date, time_raw, attachments))
    return Snapshot(_string(raw.get('chat'), 500), tuple(rows), _instant(raw.get('fetched_at')))


@dataclass(frozen=True)
class Observation:
    status: str
    events: tuple[dict, ...] = field(default=(), repr=False)
    attachments_present: bool = False


class SnapshotScanner:
    """Ordered overlap with an explicit reset after reconnect/error/sleep.

    Occurrences survive identical bodies. Ambiguous overlap is never called new.
    Caller must revalidate catalog before every scan and reset after any failed
    read; this scanner alone cannot detect an upstream catalog replacement.
    Gaps/ambiguous snapshots latch REVALIDATION_REQUIRED. Reset only after the
    caller has resolved the observation/binding uncertainty; next scan is a
    baseline. Never reset automatically on every poll.
    """
    def __init__(self, binding: Binding, *, max_gap_seconds: float = 15, timezone_name: str = 'Asia/Seoul'):
        if max_gap_seconds <= 0:
            raise ReadError('INVALID_CONFIGURATION')
        self.binding = binding
        self.max_gap_seconds = max_gap_seconds
        self.timezone = ZoneInfo(timezone_name)
        self._previous: Snapshot | None = None
        self._observed: datetime | None = None
        self._sequence = 0
        self._blocked = False

    def reset(self) -> None:
        self._previous = None
        self._observed = None
        self._blocked = False

    def scan(self, snapshot: Snapshot, *, observed_at: datetime) -> Observation:
        if self._blocked:
            return Observation('REVALIDATION_REQUIRED')
        if observed_at.tzinfo is None:
            raise ReadError('INVALID_TIMESTAMP')
        if snapshot.chat != self.binding.title:
            self.reset()
            self._blocked = True
            raise ReadError('BINDING_CHANGED')
        if abs((observed_at - snapshot.fetched_at).total_seconds()) > self.max_gap_seconds:
            self.reset()
            self._blocked = True
            return Observation('STALE_SNAPSHOT')
        previous, last = self._previous, self._observed
        self._previous, self._observed = snapshot, observed_at
        if previous is None or last is None:
            return Observation('BASELINE')
        gap = (observed_at - last).total_seconds()
        if not 0 < gap <= self.max_gap_seconds or snapshot.fetched_at < previous.fetched_at:
            self._blocked = True
            return Observation('OBSERVATION_GAP')
        if snapshot.rows == previous.rows:
            return Observation('UNCHANGED')
        if not previous.rows:
            # An empty read provides no sequence anchor; next nonempty is baseline.
            self._blocked = True
            return Observation('UNANCHORED')
        if len(snapshot.rows) < len(previous.rows):
            # A shorter view can be a UI/history rollback. Re-baselining it
            # automatically would let the old tail become "new" when restored.
            self._blocked = True
            return Observation('AMBIGUOUS_OVERLAP')
        overlaps = [size for size in range(1, min(len(previous.rows), len(snapshot.rows)) + 1)
                    if previous.rows[-size:] == snapshot.rows[:size]]
        if len(overlaps) != 1:
            self._blocked = True
            return Observation('AMBIGUOUS_OVERLAP')
        size = overlaps[0]
        anchor = snapshot.rows[:size]
        anchor_occurrences = sum(previous.rows[index:index + size] == anchor
                                 for index in range(len(previous.rows) - size + 1))
        if anchor_occurrences != 1:
            # Even a unique suffix/prefix overlap may match an earlier occurrence
            # of the same anchor. That cannot prove the view advanced past the tail.
            self._blocked = True
            return Observation('AMBIGUOUS_OVERLAP')
        added = snapshot.rows[size:]
        events = []
        for row in added:
            origin = 'unknown'
            if row.author and row.author != '(me)':
                if row.author == self.binding.partner_author:
                    origin = 'partner'
                elif row.author == self.binding.owner_author:
                    origin = 'owner'
            # Human identity alone cannot prove that an outgoing message was
            # manually typed (it may be another bot); no style-training promotion.
            source_time = None
            if row.date and row.time_raw:
                try:
                    parsed = datetime.strptime(f'{row.date} {row.time_raw}', '%Y-%m-%d %H:%M').replace(tzinfo=self.timezone)
                    if parsed <= observed_at:
                        source_time = parsed.astimezone(timezone.utc).isoformat()
                except ValueError:
                    pass
            self._sequence += 1
            events.append({'event_id': str(uuid4()), 'binding_id': self.binding.binding_id,
                           'origin': origin, 'source': 'live_poll', 'observed_at': observed_at.astimezone(timezone.utc).isoformat(),
                           'source_time': source_time, 'sequence': self._sequence, 'text': row.body,
                           'authorship': 'unknown', 'confidence': {'author': 'verified' if origin != 'unknown' else 'ambiguous',
                                                                'newness': 'verified', 'time': 'source' if source_time else 'observation_only'}})
        return Observation('APPENDED', tuple(events), any(row.attachments for row in added))
