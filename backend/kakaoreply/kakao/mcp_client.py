"""Read-only kmsg MCP client using the official Python SDK stdio transport."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import json
import logging
import math
import os
from pathlib import Path
import sys

import anyio
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .observation import Binding, ReadError, Snapshot, parse_snapshot


class _RedactSDKLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # SDK shared/session.py logs directly on the root logger; scope this
        # filter by source file so unrelated application diagnostics survive.
        path = record.pathname.replace('\\', '/')
        if any(path.endswith(suffix) for suffix in
               ('/mcp/shared/session.py', '/mcp/client/session.py', '/mcp/client/stdio/__init__.py')):
            record.msg, record.args = 'MCP_TRANSPORT_DIAGNOSTIC', ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


# SDK1.30 logs parser exceptions containing the raw input. Apply redaction at
# originating loggers, before propagation to any application/capture handlers.
for _name in ('mcp.client.stdio', 'client', ''):
    logging.getLogger(_name).addFilter(_RedactSDKLog())


class UIDispatcher:
    def __init__(self):
        self.lock = asyncio.Lock()


_DEFAULT_DISPATCHER = UIDispatcher()
_READ_ARGS = {'chat_id': 'schema-probe', 'limit': 20, 'background_safe': True,
              'deep_recovery': False, 'trace_ax': False, 'layout': 'preserve'}
_ENV = {'KMSG_MCP_STARTUP_STATUS_CHECK': 'false', 'KMSG_DEFAULT_BACKGROUND_SAFE': 'true',
        'KMSG_DEFAULT_DEEP_RECOVERY': 'false', 'KMSG_TRACE_DEFAULT': 'false', 'KMSG_DEFAULT_READ_LAYOUT': 'preserve'}


def _check_schema(tools) -> dict:
    matches = [tool for tool in tools if tool.name == 'kmsg_read']
    if len(matches) != 1:
        raise ReadError('READ_CAPABILITY_MISSING')
    schema = matches[0].inputSchema
    try:
        Draft202012Validator.check_schema(schema)
        properties = schema['properties']
        for name, value in _READ_ARGS.items():
            expected = 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'string'
            if properties[name].get('type') != expected:
                raise ValueError
        # Only local schemas are accepted: resolving a tool-provided URL would
        # grant an unintended network capability.
        def refs(value):
            if isinstance(value, dict):
                if '$ref' in value or '$dynamicRef' in value:
                    raise ValueError
                for item in value.values():
                    refs(item)
            elif isinstance(value, list):
                for item in value:
                    refs(item)
        refs(schema)
        Draft202012Validator(schema).validate(_READ_ARGS)
    except Exception:
        raise ReadError('UNSUPPORTED_READ_SCHEMA') from None
    return schema


def _payload(result) -> dict:
    if result.isError:
        raise ReadError('READ_FAILED')
    structured = result.structuredContent
    texts = [item.text for item in result.content if item.type == 'text']
    if len(texts) > 1 or len(texts) != len(result.content):
        raise ReadError('INVALID_PAYLOAD')
    text = None
    if texts:
        if len(texts[0].encode()) > 1_100_000:
            raise ReadError('PAYLOAD_TOO_LARGE')
        try:
            text = json.loads(texts[0])
        except (ValueError, RecursionError):
            raise ReadError('INVALID_PAYLOAD') from None
    if structured is not None and text is not None and structured != text:
        raise ReadError('CONFLICTING_PAYLOAD')
    value = structured if structured is not None else text
    if not isinstance(value, dict):
        raise ReadError('INVALID_PAYLOAD')
    return value


class McpReadClient:
    """No arbitrary call/send API. Construction parameters are trusted local code.

    For production use ``for_kmsg`` with a verified absolute executable path.
    Tests supply a synthetic subprocess. This client does not imply live binding,
    author, accessibility, login or permission verification.
    """
    def __init__(self, server: StdioServerParameters, *, timeout_seconds: float = 12,
                 dispatcher: UIDispatcher | None = None):
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
            raise ReadError('INVALID_CONFIGURATION')
        self._server = server
        self._timeout = timeout_seconds
        self._dispatcher = dispatcher or _DEFAULT_DISPATCHER
        self._session: ClientSession | None = None
        self._schema: dict | None = None
        self._connecting = False

    @classmethod
    def for_kmsg(cls, executable: str, **kwargs):
        path = Path(executable)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ReadError('BINARY_UNAVAILABLE')
        return cls(StdioServerParameters(command=str(path), args=['mcp-server'], env=_ENV), **kwargs)

    @asynccontextmanager
    async def connect(self):
        if self._connecting:
            raise ReadError('ALREADY_CONNECTED')
        # Child relay supplies a hard byte ceiling absent from SDK's line reader.
        relay = Path(__file__).with_name('relay.py')
        parameters = StdioServerParameters(command=sys.executable,
            args=[str(relay), self._server.command, *self._server.args],
            env={**(self._server.env or {}), **_ENV}, cwd=self._server.cwd)
        self._connecting = True  # Set before the first await, including startup.
        try:
            with open(os.devnull, 'w') as errlog:
                async with stdio_client(parameters, errlog=errlog) as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=self._timeout)) as session:
                        with anyio.fail_after(self._timeout):
                            await session.initialize()
                            tools = await session.list_tools()
                            if tools.nextCursor is not None:
                                raise ReadError('UNSUPPORTED_TOOL_PAGINATION')
                            self._schema = _check_schema(tools.tools)
                        self._session = session
                        yield self
        except asyncio.CancelledError:
            raise
        except ReadError:
            raise
        except BaseExceptionGroup as exc:
            # TaskGroup cleanup wraps errors. Preserve only our constant codes.
            def owned(group):
                for error in group.exceptions:
                    if isinstance(error, ReadError):
                        return str(error)
                    if isinstance(error, BaseExceptionGroup):
                        result = owned(error)
                        if result:
                            return result
                return None
            raise ReadError(owned(exc) or 'MCP_CONNECTION_FAILED') from None
        except Exception:
            raise ReadError('MCP_CONNECTION_FAILED') from None
        finally:
            self._session = None
            self._schema = None
            self._connecting = False

    async def read_snapshot(self, binding: Binding, *, limit: int = 100) -> Snapshot:
        if self._session is None or self._schema is None:
            raise ReadError('NOT_CONNECTED')
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ReadError('INVALID_LIMIT')
        arguments = {**_READ_ARGS, 'chat_id': binding.chat_id, 'limit': limit}
        try:
            Draft202012Validator(self._schema).validate(arguments)
            with anyio.fail_after(self._timeout):
                async with self._dispatcher.lock:
                    result = await self._session.call_tool('kmsg_read', arguments=arguments)
            snapshot = parse_snapshot(_payload(result))
            if snapshot.chat != binding.title:
                raise ReadError('BINDING_CHANGED')
            return snapshot
        except ReadError:
            self._session = None
            raise
        except asyncio.CancelledError:
            self._session = None
            raise
        except Exception:
            self._session = None
            raise ReadError('MCP_READ_FAILED') from None
