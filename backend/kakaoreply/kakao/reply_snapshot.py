"""Ephemeral bounded evidence for a reply to the latest selected chat message."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import re

from ..context_generation import Turn
from ..domain import SUFFIX
from .observation import ReadError, Row, Snapshot

CONTEXT_LIMIT = 8


@dataclass(frozen=True, repr=False)
class ReplySnapshot:
    turns: tuple[Turn, ...]
    anchor: str
    latest_key: str


def _digest(title: str, rows: tuple[Row, ...]) -> str:
    # Only used in RAM. Durable keys must be keyed again by the journal.
    fields = [(r.author, r.body, r.date, r.time_raw, r.attachments) for r in rows]
    return sha256(json.dumps([title, fields], ensure_ascii=False).encode()).hexdigest()


def make_context(snapshot: Snapshot) -> ReplySnapshot:
    if not snapshot.rows:
        raise ReadError('EMPTY_CONTEXT')
    latest = snapshot.rows[-1]
    if not latest.author or latest.author == '(me)' or snapshot.chat == '(me)':
        raise ReadError('AMBIGUOUS_AUTHOR')
    if latest.author != snapshot.chat or latest.body.rstrip().endswith(SUFFIX):
        raise ReadError('LAST_NOT_PARTNER')
    if any(r.attachments or not r.body.strip() for r in snapshot.rows):
        raise ReadError('UNSUPPORTED_CONTENT')
    if any(r.author not in (None, '(me)', snapshot.chat) for r in snapshot.rows):
        # Another named participant invalidates the confirmed one-to-one context.
        raise ReadError('AMBIGUOUS_AUTHOR')
    turns = tuple(Turn('partner' if row.author == snapshot.chat else 'unknown', row.body)
                  for row in snapshot.rows)
    return ReplySnapshot(turns, _digest(snapshot.chat, snapshot.rows), _digest(snapshot.chat, (latest,)))


def require_recent(snapshot: Snapshot, now: datetime) -> None:
    if abs((snapshot.fetched_at - now).total_seconds()) > 15:
        raise ReadError('STALE_INPUT')
    row = snapshot.rows[-1]
    try:
        source_date = datetime.strptime(row.date or '', '%Y-%m-%d')
        clock = re.fullmatch(r'(?:(오[전후])\s*)?([0-9]{1,2}):([0-5][0-9])', row.time_raw or '')
        if not clock:
            raise ValueError
        meridiem, hour, minute = clock.groups()
        parsed_hour = int(hour)
        if meridiem:
            if not 1 <= parsed_hour <= 12:
                raise ValueError
            parsed_hour = parsed_hour % 12 + (12 if meridiem == '오후' else 0)
        # kmsg captures KakaoTalk's Mac-local UI wall time. The policy window
        # timezone is a separate concern from the timezone of the source.
        source = source_date.replace(hour=parsed_hour, minute=int(minute)).astimezone()
    except ValueError:
        raise ReadError('STALE_INPUT') from None
    if not 0 <= (now - source).total_seconds() <= 1800:
        raise ReadError('STALE_INPUT')


def matches_new_echo(before: Snapshot, after: Snapshot, body: str) -> bool:
    expected_length = min(CONTEXT_LIMIT, len(before.rows) + 1)
    if before.chat != after.chat or len(after.rows) != expected_length or after.fetched_at < before.fetched_at:
        return False
    last = after.rows[-1]
    # The unresolved '(me)' marker alone is insufficient. The caller also requires
    # a scoped press and cleared input, exact submitted text, and one appended row.
    if last.author != '(me)' or last.attachments or last.body != body or not before.rows:
        return False
    # A rolled full window loses its first row. Periodic/repeated history can
    # have several possible alignments, so do not label it a confirmed append.
    overlaps = [n for n in range(1, min(len(before.rows), len(after.rows)) + 1)
                if before.rows[-n:] == after.rows[:n]]
    return overlaps == [expected_length - 1]
