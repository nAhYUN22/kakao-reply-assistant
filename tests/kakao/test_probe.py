import asyncio
import json
import os
from pathlib import Path
import sys

import pytest

from kakaoreply.kakao import ReadError
from kakaoreply.kakao.probe import Probe
import kakaoreply.kakao.probe as module


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(module, '_LOCK_PATH', tmp_path / 'ui.lock')
    executable = tmp_path / 'synthetic-kmsg'
    source = '''
import asyncio, json, os, signal, sys, time
from datetime import datetime, timezone
from pathlib import Path
root = Path(__file__).parent
mode = (root / 'mode').read_text() if (root / 'mode').exists() else 'ok'
def record(value):
    with (root / 'trace').open('a') as stream:
        stream.write(json.dumps(value) + '\\n')
if sys.argv[1:5] == ['read', '--json', '--limit', '3'] and len(sys.argv) == 6:
    (root / 'pid').write_text(str(os.getpid()))
    record({'kind': 'direct_read', 'argv': sys.argv[1:]})
    assert sys.stdin.read() == ''
    print('SYNTHETIC_PRIVATE_DIRECT_STDERR', file=sys.stderr, flush=True)
    if mode == 'hang':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(30)
    if mode == 'bad':
        print('SYNTHETIC_PRIVATE_NOT_JSON')
        sys.exit(0)
    if mode == 'error':
        print('SYNTHETIC_PRIVATE_ERROR')
        sys.exit(1)
    if mode == 'oversize':
        print('SYNTHETIC_PRIVATE' * 10000)
        sys.exit(0)
    target = sys.argv[5]
    payload = {'chat': target, 'fetched_at': datetime.now(timezone.utc).isoformat(),
               'count': 1, 'messages': [{'author': '(me)', 'body': 'SYNTHETIC_PRIVATE_BODY'}]}
    if mode == 'mismatch':
        payload.update(chat=target + ' other', messages='SYNTHETIC_PRIVATE_INVALID_MESSAGES')
    if mode == 'bad_count':
        payload['count'] = 4
    if mode == 'bad_message':
        payload['messages'] = [{'body': 42}]
    if mode == 'mcp_shape':
        payload['ok'] = True
    print(json.dumps(payload))
    sys.exit(0)
if sys.argv[1:] == ['chats', '--json', '--limit', '1000']:
    (root / 'pid').write_text(str(os.getpid()))
    record({'kind': 'catalog'})
    count_path = root / 'catalog_count'
    n = int(count_path.read_text()) + 1 if count_path.exists() else 1
    count_path.write_text(str(n))
    print('SYNTHETIC_PRIVATE_STDERR', file=sys.stderr, flush=True)
    if mode == 'hang':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(30)
    if mode == 'slow':
        time.sleep(.5)
    if mode == 'oversize':
        print('SYNTHETIC_PRIVATE' * 40000)
    elif mode == 'bad':
        print('SYNTHETIC_PRIVATE_BAD_JSON')
    elif mode == 'saturated':
        print(json.dumps({'count': 1000, 'chats': [{'chat_id': str(i), 'title': str(i)} for i in range(1000)]}))
    elif mode == 'duplicate':
        print(json.dumps({'count': 2, 'chats': [{'chat_id': 'one', 'title': 'Synthetic partner'}, {'chat_id': 'two', 'title': 'Synthetic partner'}]}))
    elif mode == 'near':
        print(json.dumps({'count': 2, 'chats': [{'chat_id': 'chat_private_id', 'title': 'Synthetic partner'}, {'chat_id': 'other', 'title': (root / 'other_title').read_text()}]}))
    elif mode in ('missing_id', 'null_id'):
        row = {'title': 'Synthetic partner'}
        if mode == 'null_id':
            row['chat_id'] = None
        print(json.dumps({'count': 1, 'chats': [row]}))
    else:
        title = 'Renamed synthetic' if ((mode == 'rename' and n >= 3) or (mode == 'rename_first' and n >= 2)) else 'Synthetic partner'
        print(json.dumps({'count': 1, 'chats': [{'chat_id': 'chat_private_id', 'title': title, 'last_message': 'SYNTHETIC_PRIVATE_PREVIEW'}]}))
    sys.exit(0)
if sys.argv[1:] != ['mcp-server']:
    record({'kind': 'FORBIDDEN_COMMAND'})
    sys.exit(2)
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
record({'kind': 'mcp_start', 'pid': os.getpid()})
server = FastMCP('synthetic-probe')
reads = 0
@server.tool()
async def kmsg_read(chat_id: str, limit: int = 20, background_safe: bool = False, deep_recovery: bool = False, trace_ax: bool = False, layout: str = 'preserve') -> CallToolResult:
    global reads
    reads += 1
    record({'kind': 'read', 'pid': os.getpid(), 'safe': background_safe, 'layout': layout, 'chat_id': chat_id})
    assert type(background_safe) is bool and not deep_recovery and not trace_ax and layout == 'preserve'
    assert os.environ['KMSG_DEFAULT_BACKGROUND_SAFE'] == 'true'
    assert chat_id == 'chat_private_id'
    messages = [{'author': '(me)', 'body': 'SYNTHETIC_PRIVATE_BASELINE'}]
    if reads == 2:
        messages.append({'author': 'Synthetic partner', 'body': 'SYNTHETIC_PRIVATE_NEW'})
    title = 'Synthetic partner extra' if mode == 'partial_read' else 'Synthetic partner'
    payload = {'ok': True, 'chat': title, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'count': len(messages), 'messages': messages}
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(payload))], structuredContent=payload)
@server.tool()
def kmsg_send(chat: str, message: str) -> str:
    record({'kind': 'FORBIDDEN_SEND'})
    raise RuntimeError('forbidden')
server.run(transport='stdio')
'''
    executable.write_text(f'#!{sys.executable}\n' + source)
    executable.chmod(0o700)
    return executable


def trace(fake):
    path = fake.parent / 'trace'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize('allow_open', [False, True])
async def test_catalog_and_two_reads_use_one_mcp_session_and_no_bodies(fake, caplog, capsys, allow_open):
    delays = []
    async def fake_sleep(seconds):
        delays.append(seconds)
    probe = Probe(str(fake), sleep=fake_sleep)
    assert probe.installed()
    assert trace(fake) == []
    choices = await probe.catalog()
    assert set(choices) == {'choices'}
    assert choices['choices'][0]['title'] == 'Synthetic partner'
    opaque = choices['choices'][0]['id']
    assert opaque != 'chat_private_id'
    result = await probe.verify(opaque, allow_open_window=True) if allow_open else await probe.verify(opaque)
    assert result == {'baseline_count': 1, 'new_count': 1, 'status': 'APPENDED'}
    assert delays == [3]
    records = trace(fake)
    assert [row['kind'] for row in records] == ['catalog', 'mcp_start', 'catalog', 'read', 'catalog', 'read']
    assert len({row['pid'] for row in records if row['kind'] == 'read'}) == 1
    assert [row['safe'] for row in records if row['kind'] == 'read'] == [not allow_open, not allow_open]
    assert 'PRIVATE' not in json.dumps(choices) + json.dumps(result) + caplog.text + str(capsys.readouterr())
    assert 'PRIVATE' not in repr(probe.__dict__)
    assert 'Synthetic partner' not in repr(probe.__dict__)
    with pytest.raises(ProcessLookupError):
        os.kill(next(row['pid'] for row in records if row['kind'] == 'mcp_start'), 0)


@pytest.mark.parametrize('mode,reads', [('rename', 1), ('rename_first', 0)])
async def test_revalidates_catalog_before_each_read(fake, mode, reads):
    (fake.parent / 'mode').write_text(mode)
    async def no_sleep(_seconds):
        pass
    probe = Probe(str(fake), sleep=no_sleep)
    selection = (await probe.catalog())['choices'][0]['id']
    with pytest.raises(ReadError, match='BINDING_CHANGED'):
        await probe.verify(selection)
    assert sum(row['kind'] == 'read' for row in trace(fake)) == reads


@pytest.mark.parametrize('mode,code', [('bad', 'CATALOG_FAILED'), ('oversize', 'CATALOG_TOO_LARGE'),
                                      ('saturated', 'CATALOG_LIMIT_REACHED'),
                                      ('missing_id', 'INVALID_PAYLOAD'), ('null_id', 'INVALID_PAYLOAD')])
async def test_catalog_bounds_and_sanitized_errors(fake, mode, code, capsys, caplog):
    (fake.parent / 'mode').write_text(mode)
    with pytest.raises(ReadError, match=code) as error:
        await Probe(str(fake)).catalog()
    assert 'PRIVATE' not in str(error.value) + caplog.text + str(capsys.readouterr())


async def test_duplicate_titles_cannot_be_verified(fake):
    (fake.parent / 'mode').write_text('duplicate')
    probe = Probe(str(fake))
    selection = (await probe.catalog())['choices'][0]['id']
    with pytest.raises(ReadError, match='AMBIGUOUS_TARGET'):
        await probe.verify(selection)
    assert [row['kind'] for row in trace(fake)] == ['catalog', 'mcp_start', 'catalog']


async def test_cross_instance_lock_held_through_two_reads(fake):
    sleeping, release = asyncio.Event(), asyncio.Event()
    async def pause(_seconds):
        sleeping.set()
        await release.wait()
    one, two = Probe(str(fake), sleep=pause), Probe(str(fake))
    selection = (await one.catalog())['choices'][0]['id']
    task = asyncio.create_task(one.verify(selection))
    await asyncio.wait_for(sleeping.wait(), 5)
    try:
        with pytest.raises(ReadError, match='PROBE_BUSY'):
            await two.catalog()
    finally:
        release.set()
        await task
    assert (await two.catalog())['choices']


async def test_os_lock_conflicts_with_another_process(fake):
    child = await asyncio.create_subprocess_exec(sys.executable, '-c',
        'import fcntl,os,sys; f=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600); fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); sys.stdin.read()',
        str(module._LOCK_PATH), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    try:
        assert await child.stdout.readline() == b'ready\n'
        with pytest.raises(ReadError, match='PROBE_BUSY'):
            await Probe(str(fake)).catalog()
        assert trace(fake) == []
    finally:
        child.stdin.close()
        await child.wait()


async def test_symlink_lock_rejected_without_modifying_target(fake):
    target = fake.parent / 'target'
    target.write_text('preserve')
    module._LOCK_PATH.symlink_to(target)
    with pytest.raises(ReadError, match='UI_LOCK_UNAVAILABLE'):
        await Probe(str(fake)).catalog()
    assert target.read_text() == 'preserve' and trace(fake) == []


async def test_timeout_kills_term_ignoring_catalog_and_unlocks(fake):
    (fake.parent / 'mode').write_text('hang')
    probe = Probe(str(fake), timeout_seconds=2)
    with pytest.raises(ReadError, match='CATALOG_TIMEOUT'):
        await probe.catalog()
    with pytest.raises(ProcessLookupError):
        os.kill(int((fake.parent / 'pid').read_text()), 0)
    assert (fake.parent / 'catalog_count').read_text() == '1'
    (fake.parent / 'mode').write_text('ok')
    assert (await probe.catalog())['choices']


async def test_default_catalog_deadline_is_separate_from_mcp(fake, monkeypatch):
    deadlines = []
    original_timeout = asyncio.timeout
    def observe_deadline(seconds):
        deadlines.append(seconds)
        return original_timeout(seconds)
    monkeypatch.setattr(module.asyncio, 'timeout', observe_deadline)
    probe = Probe(str(fake))
    assert (await probe.catalog())['choices']
    assert deadlines[0] == 30
    assert probe._timeout == 12
    assert (fake.parent / 'catalog_count').read_text() == '1'


async def test_catalog_override_can_outlast_short_mcp_deadline_without_retry(fake):
    (fake.parent / 'mode').write_text('slow')
    probe = Probe(str(fake), timeout_seconds=.1, catalog_timeout_seconds=3)
    assert (await probe.catalog())['choices']
    assert (fake.parent / 'catalog_count').read_text() == '1'


@pytest.mark.parametrize('deadline', [0, -1, float('inf'), float('nan'), 61])
def test_catalog_deadline_remains_bounded(fake, deadline):
    with pytest.raises(ReadError, match='INVALID_CONFIGURATION'):
        Probe(str(fake), catalog_timeout_seconds=deadline)
    assert trace(fake) == []


async def test_cancel_catalog_kills_process_and_unlocks(fake):
    (fake.parent / 'mode').write_text('hang')
    probe = Probe(str(fake))
    task = asyncio.create_task(probe.catalog())
    for _ in range(300):
        if (fake.parent / 'pid').exists():
            break
        await asyncio.sleep(.01)
    assert (fake.parent / 'pid').exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int((fake.parent / 'pid').read_text()), 0)
    (fake.parent / 'mode').write_text('ok')
    assert (await probe.catalog())['choices']


async def test_unknown_and_expired_selection_never_accesses_ui(fake):
    probe = Probe(str(fake))
    with pytest.raises(ReadError, match='SELECTION_EXPIRED'):
        await probe.verify('chat_private_id')
    assert trace(fake) == []
    selection = (await probe.catalog())['choices'][0]['id']
    probe._expires = 0
    with pytest.raises(ReadError, match='SELECTION_EXPIRED'):
        await probe.verify(selection)
    assert [row['kind'] for row in trace(fake)] == ['catalog']


@pytest.mark.parametrize('other_title,allow_open', [('synthetic partner', True), ('Synthetic-partner extra', True),
                                                  ('partner', True), ('Ｓｙｎｔｈｅｔｉｃ ｐａｒｔｎｅｒ', True),
                                                  ('Synthetic partner님', True), ('partner', False)])
async def test_near_name_collision_blocks_reads(fake, other_title, allow_open):
    (fake.parent / 'mode').write_text('near')
    (fake.parent / 'other_title').write_text(other_title)
    probe = Probe(str(fake))
    choices = (await probe.catalog())['choices']
    selected = next(row['id'] for row in choices if row['title'] == 'Synthetic partner')
    with pytest.raises(ReadError, match='AMBIGUOUS_TARGET'):
        await probe.verify(selected, allow_open_window=allow_open)
    assert not any(row['kind'] == 'read' for row in trace(fake))


async def test_foreground_wrong_resolved_window_never_returns_counts(fake):
    (fake.parent / 'mode').write_text('partial_read')
    probe = Probe(str(fake))
    selected = (await probe.catalog())['choices'][0]['id']
    with pytest.raises(ReadError, match='BINDING_CHANGED'):
        await probe.verify(selected, allow_open_window=True)
    assert sum(row['kind'] == 'read' for row in trace(fake)) == 1


async def test_foreground_permission_requires_an_actual_boolean(fake):
    probe = Probe(str(fake))
    for value in (1, 'true', None):
        with pytest.raises(ReadError, match='INVALID_CONFIGURATION'):
            await probe.verify('anything', allow_open_window=value)
    assert trace(fake) == []


async def test_installed_only_checks_absolute_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(module, '_LOCK_PATH', tmp_path / 'ui.lock')
    monkeypatch.setattr(module.shutil, 'which', lambda _name: None)
    assert Probe().installed() is False
    assert Probe('kmsg; false').installed() is False
    with pytest.raises(ReadError, match='BINARY_UNAVAILABLE'):
        await Probe(str(tmp_path / 'missing')).catalog()


async def test_direct_read_exact_argv_without_catalog_or_state_changes(fake, caplog, capsys):
    probe = Probe(str(fake))
    probe._choices, probe._fingerprint, probe._expires = {'keep': 'existing'}, 'fingerprint', 123
    result = await probe.direct_read('  Synthetic direct room  ')
    assert result == {'status': 'READ', 'count': 1}
    assert trace(fake) == [{'kind': 'direct_read', 'argv': ['read', '--json', '--limit', '3', 'Synthetic direct room']}]
    assert (probe._choices, probe._fingerprint, probe._expires) == ({'keep': 'existing'}, 'fingerprint', 123)
    assert 'PRIVATE' not in repr(result) + caplog.text + str(capsys.readouterr())
    assert 'Synthetic direct room' not in repr(probe.__dict__)


async def test_direct_read_shell_characters_remain_one_literal_argument(fake):
    sentinel = fake.parent / 'never-created'
    name = f'Synthetic; $(touch {sentinel})'
    assert await Probe(str(fake)).direct_read(name) == {'status': 'READ', 'count': 1}
    assert trace(fake)[0]['argv'][-1] == name
    assert not sentinel.exists()


@pytest.mark.parametrize('name', [None, 1, '', '  ', '-x', ' --json', 'a\nb', 'a\tb', 'a\x00b',
                                  'a\u2028b', 'a\u200db', 'a' * 501])
async def test_direct_read_rejects_invalid_names_before_ui(fake, name):
    with pytest.raises(ReadError, match='INVALID_CHAT_NAME'):
        await Probe(str(fake)).direct_read(name)
    assert trace(fake) == []


@pytest.mark.parametrize('mode,code', [('mismatch', 'TITLE_MISMATCH'), ('bad', 'DIRECT_READ_FAILED'),
                                      ('error', 'DIRECT_READ_FAILED'), ('oversize', 'DIRECT_READ_TOO_LARGE'),
                                      ('bad_count', 'DIRECT_READ_FAILED'), ('bad_message', 'DIRECT_READ_FAILED'),
                                      ('mcp_shape', 'DIRECT_READ_FAILED')])
async def test_direct_read_validates_title_before_messages_and_sanitizes_failures(fake, mode, code, caplog, capsys):
    (fake.parent / 'mode').write_text(mode)
    with pytest.raises(ReadError, match=code) as error:
        await Probe(str(fake)).direct_read('Synthetic direct room')
    assert len(trace(fake)) == 1 and trace(fake)[0]['kind'] == 'direct_read'
    assert 'PRIVATE' not in str(error.value) + caplog.text + str(capsys.readouterr())


async def test_direct_read_timeout_cleans_process_without_retry(fake):
    (fake.parent / 'mode').write_text('hang')
    # Leave room for macOS to launch the fixture before timing out its 30s hang.
    probe = Probe(str(fake), timeout_seconds=8)
    with pytest.raises(ReadError, match='DIRECT_READ_TIMEOUT'):
        await probe.direct_read('Synthetic direct room')
    assert len(trace(fake)) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(int((fake.parent / 'pid').read_text()), 0)
    (fake.parent / 'mode').write_text('ok')
    assert (await probe.direct_read('Synthetic direct room'))['count'] == 1


async def test_direct_read_obeys_shared_os_lock(fake):
    with module._ui_lock():
        with pytest.raises(ReadError, match='PROBE_BUSY'):
            await Probe(str(fake)).direct_read('Synthetic direct room')
    assert trace(fake) == []


async def test_direct_read_cancel_kills_process_and_unlocks(fake):
    (fake.parent / 'mode').write_text('hang')
    probe = Probe(str(fake))
    task = asyncio.create_task(probe.direct_read('Synthetic direct room'))
    for _ in range(300):
        if (fake.parent / 'pid').exists():
            break
        await asyncio.sleep(.01)
    assert (fake.parent / 'pid').exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int((fake.parent / 'pid').read_text()), 0)
    (fake.parent / 'mode').write_text('ok')
    assert (await probe.direct_read('Synthetic direct room'))['count'] == 1
