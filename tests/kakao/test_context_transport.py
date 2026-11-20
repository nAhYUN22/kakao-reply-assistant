from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest

from kakaoreply.domain import SUFFIX
from kakaoreply.kakao import ReadError, parse_snapshot
import kakaoreply.kakao.probe as module
from kakaoreply.kakao.probe import Probe
from kakaoreply.kakao.reply_snapshot import make_context, require_recent

NAME = '합성 상대'
BODY = f'합성 답장\n{SUFFIX}'
NOW = datetime(2026, 3, 12, 13, 12).astimezone()


def row(author=NAME, body='합성 질문', date='2026-03-12', time_raw='오후 1:11', **fields):
    return dict(author=author, body=body, date=date, time_raw=time_raw, **fields)


def payload(*rows, chat=NAME):
    return dict(chat=chat, fetched_at=NOW.isoformat(), count=len(rows), messages=list(rows))


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    probe = Probe(clock=lambda: NOW)
    events = []
    rows = [row('(me)', '합성 맥락'), row()]
    reads = [payload(*rows)] * 3 + [payload(*rows, row('(me)', BODY))]
    catalog = [{'chat_id': 'synthetic-id', 'title': NAME}]
    monkeypatch.setattr(module, '_LOCK_PATH', tmp_path / 'lock')
    monkeypatch.setattr(probe, '_binary', lambda: '/fixture')
    async def cli(binary, arguments, **options):
        assert binary == '/fixture'
        events.append(arguments)
        if arguments[0] == 'chats':
            return dict(chats=catalog, count=len(catalog))
        assert arguments[:4] == ('read', '--json', '--limit', '8')
        return reads.pop(0)
    monkeypatch.setattr(probe, '_run_cli_json', cli)
    @asynccontextmanager
    async def prepare(name, body, *_args):
        assert name == NAME and body == BODY
        events.append('ready')
        async def press():
            events.append('press')
        yield press
    monkeypatch.setattr(module, 'prepare_scoped_press', prepare)
    return probe, reads, catalog, events


async def test_context_direct_then_single_press_and_anchored_local_echo(bridge):
    probe, reads, catalog, events = bridge
    snapshot = await probe.reply_context(NAME)
    assert [t.author for t in snapshot.turns] == ['unknown', 'partner']
    assert events == [('read', '--json', '--limit', '8', NAME)]
    await probe.send_if_current(NAME, snapshot, BODY, lambda: events.append('claim'))
    assert events[1:] == [
        ('chats', '--json', '--limit', '1000'),
        ('read', '--json', '--limit', '8', '--keep-window', '--chat-id', 'synthetic-id'),
        'ready',
        ('read', '--json', '--limit', '8', '--background-safe', '--chat-id', 'synthetic-id'),
        'claim', 'press',
        ('read', '--json', '--limit', '8', '--background-safe', '--chat-id', 'synthetic-id')]
    assert not reads


@pytest.mark.parametrize('changes,reason', [
    (payload(chat='다른 합성 방'), 'TITLE_MISMATCH'),
    (payload(), 'EMPTY_CONTEXT'),
    (payload(row('(me)')), 'AMBIGUOUS_AUTHOR'),
    (payload(row(author=None)), 'AMBIGUOUS_AUTHOR'),
    (payload(row('합성 제삼자'), row()), 'AMBIGUOUS_AUTHOR'),
    (payload(row(body='사진', image_count=1)), 'UNSUPPORTED_CONTENT'),
    (payload(row(body=BODY)), 'LAST_NOT_PARTNER'),
])
async def test_uncertain_reads_hold_without_catalog_or_message_output(bridge, changes, reason):
    probe, reads, _, events = bridge
    reads[0] = changes
    with pytest.raises(ReadError, match=reason) as error:
        await probe.reply_context(NAME)
    assert str(error.value) == reason and len(events) == 1


@pytest.mark.parametrize('mutation,reason', [
    ('collision', 'AMBIGUOUS_TARGET'), ('stale', 'STALE_INPUT'), ('missing_date', 'STALE_INPUT'),
    ('edited_time', 'CONTEXT_CHANGED'), ('changed_after_ready', 'AMBIGUOUS_AUTHOR'),
    ('claim_denied', 'STOPPED'),
])
async def test_preattempt_failure_never_presses(bridge, mutation, reason):
    probe, reads, catalog, events = bridge
    if mutation in ('stale', 'missing_date'):
        for response in reads[:3]:
            response['messages'][-1]['date'] = '2020-01-01' if mutation == 'stale' else None
    snapshot = await probe.reply_context(NAME)
    if mutation == 'collision':
        catalog.append(dict(chat_id='second', title=NAME + '님'))
    if mutation == 'edited_time':
        reads[0] = payload(row('(me)', '합성 맥락'), row(time_raw='오후 1:10'))
    if mutation == 'changed_after_ready':
        reads[1] = payload(row(), row('(me)', '직접 답한 합성 문장'))
    def claim():
        events.append('claim')
        if mutation == 'claim_denied':
            raise ReadError('STOPPED')
    with pytest.raises(ReadError, match=reason):
        await probe.send_if_current(NAME, snapshot, BODY, claim)
    assert 'press' not in events
    assert ('claim' in events) == (mutation == 'claim_denied')


@pytest.mark.parametrize('echo', [
    payload(row()), payload(row(), row('(me)', BODY)),
    payload(row('(me)', '합성 맥락'), row(), row(NAME, BODY)),
])
async def test_press_without_an_unambiguous_new_echo_is_unknown(bridge, echo):
    probe, reads, _, events = bridge
    reads[-1] = echo
    snapshot = await probe.reply_context(NAME)
    with pytest.raises(ReadError, match='DELIVERY_UNKNOWN'):
        await probe.send_if_current(NAME, snapshot, BODY, lambda: events.append('claim'))
    assert events.count('press') == events.count('claim') == 1


def test_latest_key_stable_despite_history_growth_but_anchor_covers_context():
    first = make_context(parse_snapshot(dict(ok=True, **payload(row()))))
    second = make_context(parse_snapshot(dict(ok=True, **payload(row(body='맥락'), row()))))
    assert first.anchor != second.anchor and first.latest_key == second.latest_key


@pytest.mark.parametrize('clock, hour,minute', [('오전 12:05',0,5), ('오후12:05',12,5),
                                                 ('오후 1:10',13,10), ('00:14',0,14), ('23:00',23,0)])
def test_source_time_matches_upstream_meridiem_boundaries(clock, hour, minute):
    now = datetime(2026, 3, 12, hour, minute).astimezone()
    raw = payload(row(time_raw=clock))
    snapshot = parse_snapshot(dict(ok=True, **{**raw, 'fetched_at': now.isoformat()}))
    require_recent(snapshot, now)
    with pytest.raises(ReadError, match='STALE_INPUT'):
        require_recent(snapshot, now - timedelta(seconds=1))


@pytest.mark.parametrize('clock', ['오전 0:12', '오후 13:00', '25:12', '12', '12:02AM', None])
def test_unsupported_or_missing_source_time_holds(clock):
    snapshot = parse_snapshot(dict(ok=True, **payload(row(time_raw=clock))))
    with pytest.raises(ReadError, match='STALE_INPUT'):
        require_recent(snapshot, NOW)


@pytest.mark.parametrize('stage', ['submit', 'stop_before_claim', 'missing_controls', 'uncertain'])
async def test_subprocess_handshake_sends_no_message_argv_and_never_retries(tmp_path, monkeypatch, stage):
    import sys
    from kakaoreply.kakao import scoped_dispatch

    monkeypatch.setattr(scoped_dispatch, 'ROOT', tmp_path)
    monkeypatch.setattr(scoped_dispatch.sys, 'platform', 'darwin')
    binary = tmp_path / 'build' / 'kakaoreply-scoped-send'
    binary.parent.mkdir()
    binary.write_text(f'#!{sys.executable}\n' + """
import json
import sys
from pathlib import Path
root = Path(__file__).parent
assert len(sys.argv) == 1
payload = json.loads(sys.stdin.readline())
assert set(payload) == {'body', 'target'}
stage = (root / 'mode').read_text()
if stage == 'missing_controls':
    sys.exit(1)
print('READY', flush=True)
if sys.stdin.readline().strip() != 'SUBMIT':
    sys.exit(1)
with (root / 'presses').open('a') as stream:
    stream.write('1')
if stage == 'uncertain':
    sys.exit(1)
print('SUBMITTED', flush=True)
""")
    binary.chmod(0o700)
    (binary.parent / 'mode').write_text(stage)
    async def run():
        async with scoped_dispatch.prepare_scoped_press(NAME, BODY, 12, module._stop_process) as press:
            if stage == 'stop_before_claim':
                raise ReadError('STOPPED')
            await press()
    if stage == 'submit':
        await run()
    else:
        with pytest.raises(ReadError, match={
                'stop_before_claim': 'STOPPED', 'missing_controls': 'LIVE_SEND_UNAVAILABLE',
                'uncertain': 'DELIVERY_UNKNOWN'}[stage]):
            await run()
    presses = binary.parent / 'presses'
    if stage in ('submit', 'uncertain'):
        assert presses.read_text() == '1'
    else:
        assert not presses.exists()


async def test_repeated_full_window_does_not_establish_a_unique_echo(bridge):
    probe, reads, _, events = bridge
    identical = [row()] * 8
    reads[:] = [payload(*identical)] * 3 + [payload(*identical[1:], row('(me)', BODY))]
    snapshot = await probe.reply_context(NAME)
    with pytest.raises(ReadError, match='DELIVERY_UNKNOWN'):
        await probe.send_if_current(NAME, snapshot, BODY, lambda: events.append('claim'))
    assert events.count('press') == 1
