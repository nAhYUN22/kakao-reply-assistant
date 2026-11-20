from datetime import datetime, timedelta, timezone

import pytest

from kakaoreply.domain import validate
from kakaoreply.kakao import BindingVerifier, ReadError, SnapshotScanner, parse_snapshot

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)
CATALOG = {'count': 1, 'chats': [{'chat_id': 'chat_synthetic', 'title': 'Synthetic partner'}]}


def bind(**kw):
    return BindingVerifier().bind(CATALOG, 'chat_synthetic', one_to_one_confirmed=True, **kw)


def snapshot(bodies, at=NOW, author='Synthetic partner', **fields):
    return parse_snapshot({'ok': True, 'chat': 'Synthetic partner', 'count': len(bodies),
        'fetched_at': at.isoformat(), 'messages': [dict(author=author, body=body, **fields) for body in bodies]})


def test_baseline_ordered_overlap_repeated_occurrences_and_schema():
    scanner = SnapshotScanner(bind(partner_author='Synthetic partner', authors_confirmed=True))
    assert scanner.scan(snapshot(['anchor', 'yes']), observed_at=NOW).status == 'BASELINE'
    now = NOW + timedelta(seconds=5)
    observed = scanner.scan(snapshot(['anchor', 'yes', 'yes'], now), observed_at=now)
    assert observed.status == 'APPENDED'
    assert [e['text'] for e in observed.events] == ['yes']
    event = observed.events[0]
    assert event['origin'] == 'partner' and event['source_time'] is None
    assert event['confidence']['time'] == 'observation_only'
    validate('message-event', event)
    assert scanner.scan(snapshot(['anchor', 'yes', 'yes'], now + timedelta(seconds=1)), observed_at=now + timedelta(seconds=1)).events == ()
    scanner.reset()
    assert scanner.scan(snapshot(['new after reconnect'], now), observed_at=now).status == 'BASELINE'


@pytest.mark.parametrize('old,new', [(['yes', 'yes'], ['yes', 'yes', 'yes']), (['a'], ['b']), ([], ['b'])])
def test_ambiguous_or_unanchored_is_not_new(old, new):
    scanner = SnapshotScanner(bind())
    scanner.scan(snapshot(old), observed_at=NOW)
    later = NOW + timedelta(seconds=5)
    assert scanner.scan(snapshot(new, later), observed_at=later).events == ()


def test_sleep_gap_stale_source_and_target_change():
    scanner = SnapshotScanner(bind())
    scanner.scan(snapshot(['a']), observed_at=NOW)
    later = NOW + timedelta(seconds=30)
    assert scanner.scan(snapshot(['a', 'b'], later), observed_at=later).status == 'OBSERVATION_GAP'
    assert scanner.scan(snapshot(['a', 'b', 'c'], later), observed_at=later).status == 'REVALIDATION_REQUIRED'
    scanner.reset()
    assert scanner.scan(snapshot(['a', 'b']), observed_at=later).status == 'STALE_SNAPSHOT'
    scanner.reset()
    wrong = parse_snapshot({'ok': True, 'chat': 'Other', 'fetched_at': NOW.isoformat(), 'count': 0, 'messages': []})
    with pytest.raises(ReadError, match='BINDING_CHANGED'):
        scanner.scan(wrong, observed_at=NOW)


def test_binding_duplicate_rename_and_unverified_evidence():
    verifier = BindingVerifier()
    bound = verifier.bind(CATALOG, 'chat_synthetic', one_to_one_confirmed=True)
    verifier.verify(bound, CATALOG)
    with pytest.raises(ReadError, match='BINDING_CHANGED'):
        verifier.verify(bound, {'count': 1, 'chats': [{'chat_id': 'chat_synthetic', 'title': 'Renamed'}]})
    with pytest.raises(ReadError, match='AMBIGUOUS_TARGET'):
        verifier.bind({'count': 2, 'chats': CATALOG['chats'] + [{'chat_id': 'chat_other', 'title': 'Synthetic partner'}]},
                      'chat_synthetic', one_to_one_confirmed=True)
    with pytest.raises(ReadError, match='AMBIGUOUS_AUTHOR'):
        bind(owner_author='(me)', authors_confirmed=True)
    assert bind(owner_author='Owner', authors_confirmed=False).owner_author is None


def test_me_and_bot_echo_not_promoted_to_owner_or_training():
    scanner = SnapshotScanner(bind(owner_author='Synthetic owner', authors_confirmed=True))
    scanner.scan(snapshot(['anchor'], author='(me)'), observed_at=NOW)
    now = NOW + timedelta(seconds=5)
    event = scanner.scan(snapshot(['anchor', 'reply'], now, author='(me)'), observed_at=now).events[0]
    assert event['origin'] == 'unknown' and event['authorship'] == 'unknown'
    assert event['confidence']['author'] == 'ambiguous'


def test_transcript_rollback_does_not_replay_previously_emitted_message():
    scanner = SnapshotScanner(bind())
    scanner.scan(snapshot(['a']), observed_at=NOW)
    at = NOW + timedelta(seconds=1)
    assert len(scanner.scan(snapshot(['a', 'b'], at), observed_at=at).events) == 1
    at += timedelta(seconds=1)
    assert scanner.scan(snapshot(['a'], at), observed_at=at).status == 'AMBIGUOUS_OVERLAP'
    at += timedelta(seconds=1)
    assert scanner.scan(snapshot(['a', 'b'], at), observed_at=at).status == 'REVALIDATION_REQUIRED'


def test_shrink_to_repeated_tail_does_not_replay_old_occurrences():
    scanner = SnapshotScanner(bind())
    scanner.scan(snapshot(['a']), observed_at=NOW)
    at = NOW + timedelta(seconds=1)
    result = scanner.scan(snapshot(['a', 'b', 'a'], at), observed_at=at)
    assert [event['text'] for event in result.events] == ['b', 'a']
    at += timedelta(seconds=1)
    assert scanner.scan(snapshot(['a'], at), observed_at=at).status == 'AMBIGUOUS_OVERLAP'
    at += timedelta(seconds=1)
    assert scanner.scan(snapshot(['a', 'b', 'a'], at), observed_at=at).status == 'REVALIDATION_REQUIRED'


@pytest.mark.parametrize('previous,current', [(['a', 'b', 'a'], ['a', 'b', 'c']),
                                             (['a', 'b', 'a', 'b'], ['a', 'b', 'c', 'd'])])
def test_repeated_internal_anchor_does_not_prove_append(previous, current):
    scanner = SnapshotScanner(bind())
    scanner.scan(snapshot(previous), observed_at=NOW)
    at = NOW + timedelta(seconds=1)
    result = scanner.scan(snapshot(current, at), observed_at=at)
    assert result.status == 'AMBIGUOUS_OVERLAP' and result.events == ()
    at += timedelta(seconds=1)
    assert scanner.scan(snapshot(current + ['next'], at), observed_at=at).status == 'REVALIDATION_REQUIRED'


def test_attachments_and_time_retained_as_evidence():
    scanner = SnapshotScanner(bind())
    scanner.scan(snapshot(['anchor'], date='2026-11-20', time_raw='08:59', has_image=True), observed_at=NOW)
    now = NOW + timedelta(seconds=5)
    result = scanner.scan(snapshot(['anchor', 'image'], now, date='2026-11-20', time_raw='08:59', has_image=True), observed_at=now)
    assert result.attachments_present and result.events[0]['source_time'] == '2026-11-19T23:59:00+00:00'


@pytest.mark.parametrize('change', [{'count': 2}, {'messages': [{'body': 123}]}, {'fetched_at': 'not a date'}, {'ok': False}])
def test_malformed_payloads(change):
    payload = {'ok': True, 'chat': 'Synthetic partner', 'fetched_at': NOW.isoformat(), 'count': 1, 'messages': [{'body': 'ok'}]}
    payload.update(change)
    with pytest.raises(ReadError):
        parse_snapshot(payload)
