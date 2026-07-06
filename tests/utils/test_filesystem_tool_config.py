# Copyright (c) ModelScope Contributors. All rights reserved.
"""FileSystemTool config: include aliases and grep/glob registration."""

import asyncio
import tempfile

from omegaconf import OmegaConf

from ms_agent.tools.filesystem_tool import FileSystemTool


def test_include_short_aliases_expand_to_canonical_names():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            cfg = OmegaConf.create({
                'output_dir': td,
                'tools': {
                    'file_system': {
                        'mcp': False,
                        'include': ['read', 'write', 'glob'],
                    },
                },
            })
            fs = FileSystemTool(cfg)
            tools = await fs.get_tools()
            names = [t['tool_name'] for t in tools['file_system']]
            assert 'read_file' in names
            assert 'write_file' in names
            assert 'glob' in names
            assert 'grep' not in names
            assert 'read' not in names
            assert 'write' not in names

    asyncio.run(_run())


def test_grep_glob_listed_with_full_names():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            cfg = OmegaConf.create({
                'output_dir': td,
                'tools': {
                    'file_system': {
                        'mcp': False,
                        'include': ['grep', 'glob'],
                    },
                },
            })
            fs = FileSystemTool(cfg)
            tools = await fs.get_tools()
            names = [t['tool_name'] for t in tools['file_system']]
            assert names == ['grep', 'glob']

    asyncio.run(_run())
