import asyncio
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from kakaoreply.adapters import FakeTransport, MockLLM
from kakaoreply.crypto import DataCipher
from kakaoreply.engine import Engine
from kakaoreply.storage import Journal, StorageError
from kakaoreply.storage_setup import open_journal

NOW = datetime(2026, 11, 20, 3, tzinfo=timezone.utc)


@pytest.fixture
def cipher():
    return DataCipher(b'k' * 32, 'synthetic-key')


def v1_database(path):
    db = sqlite3.connect(path)
    db.executescript('''
    CREATE TABLE schema_version(version INTEGER NOT NULL);
    INSERT INTO schema_version VALUES(1);
    CREATE TABLE jobs(id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
    CREATE TABLE events(digest TEXT PRIMARY KEY);
    CREATE TABLE attempts(job_id TEXT PRIMARY KEY, at TEXT NOT NULL, session_id TEXT NOT NULL);
    CREATE TABLE runtime(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    job = {'job_id': 'old-job', 'state': 'DISPATCHING', 'attempt_count': 1,
           'reason_codes': [], 'created_at': NOW.isoformat(), 'updated_at': NOW.isoformat(),
           'due_at': None, 'incoming_count': 1}
    db.execute('INSERT INTO jobs VALUES(?,?)', ('old-job', json.dumps(job)))
    db.execute('INSERT INTO attempts VALUES(?,?,?)', ('old-job', NOW.isoformat(), 'old-session'))
    db.execute('INSERT INTO runtime VALUES(?,?)', ('session_id', json.dumps('old-session')))
    db.execute('INSERT INTO events VALUES(?)', ('existing-digest',))
    db.commit()
    db.close()


def test_migration_preserves_unknown_attempts_and_metadata(tmp_path, cipher):
    path = str(tmp_path / 'v1.sqlite')
    v1_database(path)
    with_journal = Journal(path, cipher=cipher)
    engine = Engine(with_journal)
    assert engine.jobs['old-job']['state'] == 'DELIVERY_UNKNOWN'
    assert engine.state()['mode'] == 'off'
    assert engine.state()['paused_reason'] == 'DELIVERY_UNKNOWN'
    assert with_journal.attempts() == [('old-job', NOW.isoformat(), 'old-session')]
    assert with_journal.db.execute('SELECT * FROM events').fetchall() == [('existing-digest',)]
    assert with_journal.db.execute('SELECT version FROM schema_version').fetchone() == (2,)
    engine.close()
    reopened = Journal(path, cipher=cipher)
    assert len(reopened.attempts()) == 1
    reopened.close()


def test_failed_migration_rolls_back_and_unlocks(tmp_path, cipher):
    path = str(tmp_path / 'v1.sqlite')
    v1_database(path)
    def locked():
        raise RuntimeError('SYNTHETIC_SECRET_KEYCHAIN_ERROR')
    with pytest.raises(StorageError, match='KEY_UNAVAILABLE'):
        Journal(path, cipher=cipher, key_check=locked)
    db = sqlite3.connect(path)
    assert db.execute('SELECT version FROM schema_version').fetchone() == (1,)
    assert db.execute("SELECT name FROM sqlite_master WHERE name='sensitive'").fetchone() is None
    db.close()
    Journal(path).close()


@pytest.mark.parametrize('mode', ['missing', 'wrong-id', 'wrong-key'])
def test_encrypted_database_never_falls_back(tmp_path, cipher, mode):
    path = str(tmp_path / 'encrypted.sqlite')
    journal = Journal(path, cipher=cipher)
    journal.save_body('reply', 'synthetic-job', 'SYNTHETIC_PRIVATE_BODY', NOW)
    journal.close()
    supplied = {'missing': None, 'wrong-id': DataCipher(b'k' * 32, 'other'),
                'wrong-key': DataCipher(b'x' * 32, 'synthetic-key')}[mode]
    with pytest.raises(StorageError):
        Journal(path, cipher=supplied)
    journal = Journal(path, cipher=cipher)
    assert journal.load_body('reply', 'synthetic-job', NOW) == 'SYNTHETIC_PRIVATE_BODY'
    journal.close()


def test_plaintext_not_in_database_wal_or_errors(tmp_path, cipher):
    path = str(tmp_path / 'encrypted.sqlite')
    journal = Journal(path, cipher=cipher)
    text = 'SYNTHETIC_PRIVATE_BODY_338812'
    journal.save_body('reply', 'one', text, NOW)
    assert text not in '\n'.join(journal.db.iterdump())
    for file in tmp_path.iterdir():
        assert text.encode() not in file.read_bytes()
    row = journal.db.execute('SELECT ciphertext FROM sensitive').fetchone()[0]
    journal.db.execute('UPDATE sensitive SET ciphertext=?', (row[:-1] + bytes([row[-1] ^ 1]),))
    journal.db.commit()
    with pytest.raises(StorageError, match='ENCRYPTED_READ_FAILED'):
        journal.load_body('reply', 'one', NOW)
    journal.close()


@pytest.mark.asyncio
async def test_reply_recovers_with_same_key_and_delete_keeps_attempt(tmp_path, cipher):
    path = str(tmp_path / 'encrypted.sqlite')
    engine = Engine(Journal(path, cipher=cipher))
    await engine.start('auto')
    await engine.message('합성 산책 이야기')
    await engine.advance(600)
    job_id = next(iter(engine.jobs))
    expected = engine.detail(job_id)['reply_text']
    assert expected.endswith('— 부재중 AI 답장')
    assert not engine.texts
    engine.close()
    engine = Engine(Journal(path, cipher=cipher))
    assert engine.detail(job_id)['reply_text'] == expected
    await engine.delete_reply(job_id)
    assert engine.detail(job_id)['reply_text'] is None
    assert engine.jobs[job_id]['attempt_count'] == 1
    assert len(engine.journal.attempts()) == 1
    engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('encrypted', [True, False])
async def test_delete_forgets_all_runtime_copies(tmp_path, cipher, encrypted):
    engine = Engine(Journal(str(tmp_path / 'a.sqlite'), cipher=cipher if encrypted else None))
    await engine.start('auto')
    await engine.message('합성')
    await engine.advance(600)
    job_id = next(iter(engine.jobs))
    assert engine.transport.attempts[0]['text']
    await engine.delete_reply(job_id)
    assert engine.detail(job_id)['reply_text'] is None
    assert 'text' not in engine.transport.attempts[0]
    assert 'text' not in engine.transport.echoes[0]
    assert len(engine.journal.attempts()) == 1
    engine.close()


@pytest.mark.asyncio
async def test_ttl_expiry_and_metadata_kept(tmp_path, cipher):
    engine = Engine(Journal(str(tmp_path / 'a.sqlite'), cipher=cipher))
    await engine.start('auto')
    await engine.message('합성')
    await engine.advance(600)
    job_id = next(iter(engine.jobs))
    for _ in range(7):
        await engine.advance(86400)
    assert engine.detail(job_id)['reply_text'] is None
    assert len(engine.journal.attempts()) == 1
    assert 'text' not in engine.transport.attempts[0]
    engine.close()


@pytest.mark.asyncio
async def test_locked_key_after_generation_prevents_dispatch(tmp_path, cipher):
    locked = False
    def check():
        if locked:
            raise RuntimeError('SYNTHETIC_PRIVATE_BACKEND_ERROR')
    engine = Engine(Journal(str(tmp_path / 'a.sqlite'), cipher=cipher, key_check=check))
    class LockingLLM(MockLLM):
        async def generate(self, messages):
            nonlocal locked
            result = await super().generate(messages)
            locked = True
            return result
    engine.llm = LockingLLM()
    await engine.start('auto')
    await engine.message('합성')
    await engine.advance(600)
    assert not engine.transport.attempts
    assert not engine.journal.attempts()
    assert engine.state()['mode'] == 'off'
    assert engine.state()['paused_reason'] == 'STORAGE_UNAVAILABLE'
    assert next(iter(engine.jobs.values()))['state'] == 'FAILED_BEFORE_DISPATCH'
    engine.close()


@pytest.mark.asyncio
async def test_encryption_failure_prevents_dispatch(tmp_path, cipher, monkeypatch):
    engine = Engine(Journal(str(tmp_path / 'a.sqlite'), cipher=cipher))
    def broken(*args):
        raise RuntimeError('SYNTHETIC_PRIVATE_CIPHER_ERROR')
    monkeypatch.setattr(DataCipher, 'encrypt', broken)
    await engine.start('auto')
    await engine.message('합성')
    await engine.advance(600)
    assert not engine.transport.attempts
    assert engine.state()['paused_reason'] == 'STORAGE_UNAVAILABLE'
    engine.close()


def test_factory_rechecks_key_without_provisioning(tmp_path):
    class Provider:
        key = b'x' * 32
        def get_key(self, key_id):
            return self.key
    provider = Provider()
    journal = open_journal(str(tmp_path / 'a.sqlite'), mode='keychain', key_id='synthetic', provider=provider)
    provider.key = b'y' * 32
    with pytest.raises(StorageError):
        journal.save_body('reply', 'one', 'SYNTHETIC', NOW)
    assert journal.db.execute('SELECT count(*) FROM sensitive').fetchone()[0] == 0
    journal.close()


def test_future_schema_is_not_modified(tmp_path):
    path = str(tmp_path / 'future.sqlite')
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE schema_version(version INTEGER NOT NULL)')
    db.execute('INSERT INTO schema_version VALUES(900)')
    db.commit(); db.close()
    with pytest.raises(StorageError, match='UNSUPPORTED_DATABASE_VERSION'):
        Journal(path)
    db = sqlite3.connect(path)
    assert db.execute('SELECT version FROM schema_version').fetchone()[0] == 900
    assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 1
    db.close()


@pytest.mark.asyncio
async def test_delete_during_generation_prevents_body_resurrection(tmp_path, cipher):
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowLLM(MockLLM):
        async def generate(self, messages):
            entered.set()
            await release.wait()
            return await super().generate(messages)
    engine = Engine(Journal(str(tmp_path / 'a.sqlite'), cipher=cipher), llm=SlowLLM())
    await engine.start('auto')
    await engine.message('합성')
    task = asyncio.create_task(engine.advance(600))
    await entered.wait()
    job_id = next(iter(engine.jobs))
    await engine.delete_reply(job_id)
    release.set()
    await task
    assert engine.detail(job_id)['reply_text'] is None
    assert engine.jobs[job_id]['reason_codes'] == ['BODY_DELETED']
    assert not engine.transport.attempts
    assert not engine.journal.attempts()
    engine.close()


@pytest.mark.asyncio
async def test_delete_during_dispatch_is_rejected_without_hiding_result(tmp_path, cipher):
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowTransport(FakeTransport):
        async def send(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().send(**kwargs)
    engine = Engine(Journal(str(tmp_path / 'a.sqlite'), cipher=cipher), transport=SlowTransport())
    await engine.start('auto')
    await engine.message('합성')
    task = asyncio.create_task(engine.advance(600))
    await entered.wait()
    job_id = next(iter(engine.jobs))
    with pytest.raises(ValueError, match='DISPATCH_IN_PROGRESS'):
        await engine.delete_reply(job_id)
    assert engine.detail(job_id)['reply_text']
    release.set()
    await task
    assert engine.jobs[job_id]['state'] == 'CONFIRMED_LOCAL'
    await engine.delete_reply(job_id)
    assert engine.detail(job_id)['reply_text'] is None
    assert len(engine.journal.attempts()) == 1
    engine.close()
