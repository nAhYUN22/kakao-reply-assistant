import asyncio
import json
import os
from pathlib import Path
import sys

import pytest
from mcp import StdioServerParameters
from mcp.types import Tool

from kakaoreply.kakao import BindingVerifier, McpReadClient, ReadError
from kakaoreply.kakao.mcp_client import _check_schema

SERVER = Path(__file__).with_name('fake_mcp_server.py')


def binding():
    return BindingVerifier().bind({'count': 1, 'chats': [{'chat_id': 'chat_synthetic', 'title': 'Synthetic partner'}]},
                                  'chat_synthetic', one_to_one_confirmed=True)


def client(tmp_path, mode='ok', timeout=3):
    return McpReadClient(StdioServerParameters(command=sys.executable, args=[str(SERVER)],
        env={'FAKE_MODE': mode, 'FAKE_PID': str(tmp_path / 'pid'), 'FAKE_CALLS': str(tmp_path / 'calls')}),
        timeout_seconds=timeout)


def assert_dead(tmp_path):
    pid = int((tmp_path / 'pid').read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_real_stdio_handshake_read_and_shutdown(tmp_path, capsys):
    adapter = client(tmp_path)
    async with adapter.connect():
        snapshot = await adapter.read_snapshot(binding())
        assert snapshot.rows[0].body == 'Synthetic hello'
        with pytest.raises(ReadError, match='ALREADY_CONNECTED'):
            async with adapter.connect():
                pytest.fail('duplicate session opened')
    calls = [json.loads(line) for line in (tmp_path / 'calls').read_text().splitlines()]
    assert calls == [{'name': 'kmsg_read', 'chat_id': 'chat_synthetic', 'limit': 100,
                      'background_safe': True, 'deep_recovery': False, 'trace_ax': False, 'layout': 'preserve'}]
    assert not hasattr(adapter, 'call_tool') and not hasattr(adapter, 'send')
    assert_dead(tmp_path)
    assert 'PRIVATE' not in str(capsys.readouterr())
    with pytest.raises(ReadError, match='NOT_CONNECTED'):
        await adapter.read_snapshot(binding())


async def test_foreground_is_explicit_per_call_and_protected_environment_remains(tmp_path):
    adapter = client(tmp_path)
    async with adapter.connect():
        await adapter.read_snapshot(binding(), allow_open_window=True)
        await adapter.read_snapshot(binding())
        for value in (1, 'true', None):
            with pytest.raises(ReadError, match='INVALID_CONFIGURATION'):
                await adapter.read_snapshot(binding(), allow_open_window=value)
    calls = [json.loads(line) for line in (tmp_path / 'calls').read_text().splitlines()]
    assert [call['background_safe'] for call in calls] == [False, True]
    assert all(call['deep_recovery'] is False and call['trace_ax'] is False and call['layout'] == 'preserve' for call in calls)
    assert_dead(tmp_path)


async def test_foreground_partial_title_result_is_not_accepted(tmp_path):
    adapter = client(tmp_path, 'partial_target')
    with pytest.raises(ReadError, match='BINDING_CHANGED'):
        async with adapter.connect():
            await adapter.read_snapshot(binding(), allow_open_window=True)
    assert_dead(tmp_path)


@pytest.mark.parametrize('mode,code', [('error', 'READ_FAILED'), ('conflict', 'CONFLICTING_PAYLOAD'),
                                      ('wrong_target', 'BINDING_CHANGED'), ('missing', 'READ_CAPABILITY_MISSING'),
                                      ('delay', 'MCP_READ_FAILED'), ('malformed', 'MCP_READ_FAILED'),
                                      ('invalid_request', 'MCP_READ_FAILED'),
                                      ('oversize', 'MCP_READ_FAILED')])
async def test_fail_closed_and_private_errors(tmp_path, caplog, capsys, mode, code):
    adapter = client(tmp_path, mode)
    with pytest.raises(ReadError, match=code) as error:
        async with adapter.connect():
            await adapter.read_snapshot(binding())
    assert_dead(tmp_path)
    assert 'PRIVATE' not in str(error.value) + caplog.text + str(capsys.readouterr())
    if (tmp_path / 'calls').exists():
        assert 'FORBIDDEN_SEND' not in (tmp_path / 'calls').read_text()


@pytest.mark.parametrize('mode', ['delay', 'ignore_term'])
async def test_cancel_cleans_process_tree(tmp_path, mode):
    adapter = client(tmp_path, mode)
    async def run():
        async with adapter.connect():
            await adapter.read_snapshot(binding())
    task = asyncio.create_task(run())
    # Bounded startup wait, no real process or wall clock message scheduling.
    for _ in range(300):
        if (tmp_path / 'calls').exists():
            break
        await asyncio.sleep(.01)
    assert (tmp_path / 'calls').exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_dead(tmp_path)


def test_schema_requires_background_safe_and_rejects_external_refs():
    with pytest.raises(ReadError, match='UNSUPPORTED_READ_SCHEMA'):
        _check_schema([Tool(name='kmsg_read', inputSchema={'type': 'object', 'properties': {'chat_id': {'type': 'string'}}})])
    with pytest.raises(ReadError, match='UNSUPPORTED_READ_SCHEMA'):
        _check_schema([Tool(name='kmsg_read', inputSchema={'$ref': 'https://example.invalid/schema'})])


def test_does_not_resolve_path_or_run_shell():
    with pytest.raises(ReadError, match='BINARY_UNAVAILABLE'):
        McpReadClient.for_kmsg('kmsg; touch /tmp/never')
