"""A stdio server's child process must be spawnable and networked: the MCP
SDK's default child env strips proxy/index settings, and a backend launched
with a minimal PATH cannot see the user's uvx at all."""
import os
from unittest import mock

import pytest

from ms_agent.tools.mcp_client import (stdio_child_env, resolve_stdio_command)


def test_child_env_carries_network_settings_but_not_credentials():
    parent = {
        'PATH': '/usr/bin',
        'HOME': '/home/tester',
        'HTTPS_PROXY': 'http://127.0.0.1:7890',
        'UV_DEFAULT_INDEX': 'https://mirror.example/simple',
        'OPENAI_API_KEY': 'must-not-leak',
    }
    with mock.patch.dict(os.environ, parent, clear=True):
        env = stdio_child_env(None)
    assert env['HTTPS_PROXY'] == 'http://127.0.0.1:7890'
    assert env['UV_DEFAULT_INDEX'] == 'https://mirror.example/simple'
    assert 'OPENAI_API_KEY' not in env

    # The server's configured env wins per key.
    with mock.patch.dict(os.environ, parent, clear=True):
        env = stdio_child_env({'HTTPS_PROXY': 'http://other:1'})
    assert env['HTTPS_PROXY'] == 'http://other:1'


def test_command_is_found_in_user_bin_dirs_when_path_is_minimal(tmp_path):
    exe = tmp_path / 'uvx'
    exe.write_text('#!/bin/sh\n')
    exe.chmod(0o755)
    with mock.patch.dict(os.environ, {'PATH': '/usr/bin'}, clear=True), \
            mock.patch('ms_agent.tools.mcp_client._STDIO_EXTRA_BIN_DIRS',
                       (str(tmp_path), )):
        assert resolve_stdio_command('uvx') == str(exe)


def test_missing_command_names_what_was_searched(tmp_path):
    with mock.patch.dict(os.environ, {'PATH': '/usr/bin'}, clear=True), \
            mock.patch('ms_agent.tools.mcp_client._STDIO_EXTRA_BIN_DIRS',
                       (str(tmp_path), )):
        with pytest.raises(FileNotFoundError) as err:
            resolve_stdio_command('no-such-tool-xyz')
    message = str(err.value)
    assert 'no-such-tool-xyz' in message
    assert str(tmp_path) in message
