# Copyright (c) ModelScope Contributors. All rights reserved.
"""MCP context ownership during normal and interrupted stdio startup."""
import asyncio
import sys

import pytest
from anyio import fail_after

from ms_agent.tools.mcp_client import MCPClient


@pytest.fixture
def stdio_servers(tmp_path):
    server = tmp_path / 'server.py'
    server.write_text(
        "import os, pathlib, sys, time\n"
        "pathlib.Path(sys.argv[2]).write_text(str(os.getpid()))\n"
        "if sys.argv[1] == 'pending':\n"
        "    time.sleep(120)\n"
        "from mcp.server.fastmcp import FastMCP\n"
        "server = FastMCP('lifecycle-test')\n"
        "@server.tool()\n"
        "def ping() -> str:\n"
        "    return 'pong'\n"
        "server.run(transport='stdio')\n",
        encoding='utf-8')
    return {
        name: {
            'command': sys.executable,
            'args': [str(server), name, str(tmp_path / name)],
        }
        for name in ('ready', 'pending')
    }


@pytest.mark.asyncio
async def test_cancelled_entry_closes_already_connected_servers(
        stdio_servers, tmp_path):
    client = MCPClient({'mcpServers': stdio_servers})
    owners = []

    async def use_client():
        async with client:
            pytest.fail('entry should still be waiting for the pending server')

    entering = asyncio.create_task(use_client())
    try:
        with fail_after(30):
            while not (client.is_connected('ready')
                       and (tmp_path / 'pending').exists()):
                await asyncio.sleep(0.01)
        owners = list(client._server_tasks.values())
        assert await client.call_tool('ready', 'ping', {}) == 'pong'
        assert not entering.done()

        entering.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(entering, 20)

        assert not client.sessions
        assert not client._server_tasks
        assert not client._server_shutdown
        assert all(task.done() for task in owners)
    finally:
        # Keep a failing regression from leaving real MCP subprocesses behind.
        if not entering.done():
            entering.cancel()
        await asyncio.gather(entering, return_exceptions=True)
        await client.cleanup()


@pytest.mark.asyncio
async def test_normal_exit_closes_connected_servers(stdio_servers):
    stdio_servers['pending']['args'][1] = 'ready'
    client = MCPClient({'mcpServers': stdio_servers})
    with fail_after(30):
        async with client as connected:
            assert connected is client
            owners = list(client._server_tasks.values())
            assert len(owners) == 2
            for name in stdio_servers:
                assert await client.call_tool(name, 'ping', {}) == 'pong'

    assert not client.sessions
    assert not client._server_tasks
    assert not client._server_shutdown
    assert all(task.done() for task in owners)
