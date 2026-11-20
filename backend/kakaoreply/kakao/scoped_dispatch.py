"""Handshake with a fixed, exact-window macOS AX sender, never a global keystroke."""
import asyncio
from contextlib import asynccontextmanager
import json
import sys

from ..domain import ROOT
from .observation import ReadError


@asynccontextmanager
async def prepare_scoped_press(target, body, timeout, stop_process):
    if sys.platform != 'darwin':
        raise ReadError('LIVE_SEND_UNAVAILABLE')
    process = None
    try:
        try:
            async with asyncio.timeout(timeout):
                process = await asyncio.create_subprocess_exec(
                    str(ROOT / 'build' / 'kakaoreply-scoped-send'),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
                request = json.dumps({'target': target, 'body': body}, ensure_ascii=False).encode()
                process.stdin.write(request + b'\n')
                await process.stdin.drain()
                if await process.stdout.readline() != b'READY\n':
                    raise ReadError('LIVE_SEND_UNAVAILABLE')
        except (TimeoutError, OSError):
            raise ReadError('LIVE_SEND_UNAVAILABLE') from None

        async def submit():
            async with asyncio.timeout(timeout):
                process.stdin.write(b'SUBMIT\n')
                await process.stdin.drain()
                if await process.stdout.readline() != b'SUBMITTED\n' or await process.wait() != 0:
                    raise ReadError('DELIVERY_UNKNOWN')

        yield submit
    finally:
        if process is not None:
            await stop_process(process)
