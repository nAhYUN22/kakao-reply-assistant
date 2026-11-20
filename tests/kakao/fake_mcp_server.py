"""Synthetic server; never imports kmsg or opens KakaoTalk."""
import asyncio
import json
import os
import signal
from pathlib import Path
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

server = FastMCP('synthetic-kmsg-contract')
mode = os.environ.get('FAKE_MODE', 'ok')
if mode == 'ignore_term':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if os.environ.get('FAKE_PID'):
    Path(os.environ['FAKE_PID']).write_text(str(os.getpid()))


@server.tool()
async def kmsg_read(chat_id: str, limit: int = 20, background_safe: bool = False,
                    deep_recovery: bool = False, trace_ax: bool = False,
                    layout: str = 'preserve') -> CallToolResult:
    if os.environ.get('FAKE_CALLS'):
        with open(os.environ['FAKE_CALLS'], 'a') as stream:
            stream.write(json.dumps({'name': 'kmsg_read', 'chat_id': chat_id, 'limit': limit,
                'background_safe': background_safe, 'deep_recovery': deep_recovery,
                'trace_ax': trace_ax, 'layout': layout}) + '\n')
    print('SYNTHETIC_PRIVATE_STDERR', file=sys.stderr, flush=True)
    assert os.environ['KMSG_MCP_STARTUP_STATUS_CHECK'] == 'false'
    assert os.environ['KMSG_DEFAULT_BACKGROUND_SAFE'] == 'true'
    if mode in ('delay', 'ignore_term'):
        await asyncio.sleep(30)
    if mode == 'malformed':
        print('SYNTHETIC_PRIVATE_INVALID_JSON', flush=True)
        await asyncio.sleep(30)
    if mode == 'invalid_request':
        print(json.dumps({'jsonrpc': '2.0', 'id': 990, 'method': 'sampling/createMessage',
                          'params': {'messages': 'SYNTHETIC_PRIVATE_BAD_REQUEST'}}), flush=True)
        await asyncio.sleep(30)
    if mode == 'oversize':
        print('X' * 1_200_001, flush=True)
        await asyncio.sleep(30)
    if mode == 'error':
        return CallToolResult(isError=True, content=[TextContent(type='text', text='SYNTHETIC_PRIVATE_ERROR')])
    payload = {'ok': True, 'chat': 'Synthetic partner', 'fetched_at': '2026-11-20T00:00:00Z',
               'count': 1, 'messages': [{'author': 'Synthetic partner', 'body': 'Synthetic hello'}]}
    if mode == 'wrong_target':
        payload['chat'] = 'Other synthetic person'
    text = json.dumps(payload)
    if mode == 'conflict':
        text = '{}'
    return CallToolResult(content=[TextContent(type='text', text=text)], structuredContent=payload)


@server.tool()
def kmsg_send(chat: str, message: str, confirm: bool = False) -> str:
    if os.environ.get('FAKE_CALLS'):
        with open(os.environ['FAKE_CALLS'], 'a') as stream:
            stream.write('FORBIDDEN_SEND\n')
    raise RuntimeError('SEND_MUST_NEVER_BE_CALLED')


if mode == 'missing':
    server.remove_tool('kmsg_read')
if __name__ == '__main__':
    server.run(transport='stdio')
