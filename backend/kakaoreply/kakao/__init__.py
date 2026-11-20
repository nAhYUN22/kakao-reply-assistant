"""M2 read-only MCP and synthetic observation contracts; not engine activation."""
from .mcp_client import McpReadClient, UIDispatcher
from .observation import Binding, BindingVerifier, Observation, ReadError, Snapshot, SnapshotScanner, parse_snapshot

__all__ = ['Binding', 'BindingVerifier', 'McpReadClient', 'Observation', 'ReadError',
           'Snapshot', 'SnapshotScanner', 'UIDispatcher', 'parse_snapshot']
