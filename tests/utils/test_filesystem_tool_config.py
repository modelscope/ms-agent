# Copyright (c) ModelScope Contributors. All rights reserved.
"""FileSystemTool config: include aliases and grep/glob registration."""

import asyncio
import json
import os
import shutil
import tempfile

import pytest
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


@pytest.mark.skipif(not shutil.which('rg'), reason='rg not installed')
def test_grep_hyphen_prefixed_pattern_uses_rg_e_flag():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sample = os.path.join(td, 'sample.js')
            with open(sample, 'w', encoding='utf-8') as f:
                f.write('-import foo from "bar"\n')

            cfg = OmegaConf.create({
                'output_dir': td,
                'tools': {
                    'file_system': {
                        'mcp': False,
                        'include': ['grep'],
                    },
                },
            })
            fs = FileSystemTool(cfg)
            raw = await fs.grep(
                pattern='-import',
                path='sample.js',
                output_mode='content',
            )
            result = json.loads(raw)
            assert result['success'] is True
            assert '-import' in result['output']

    asyncio.run(_run())


def test_edit_file_requires_path():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            cfg = OmegaConf.create({
                'output_dir': td,
                'tools': {
                    'file_system': {
                        'mcp': False,
                        'include': ['edit'],
                    },
                },
            })
            fs = FileSystemTool(cfg)
            result = await fs.edit_file(
                old_string='a',
                new_string='b',
            )
            assert result == 'Error: `path` is required.'

    asyncio.run(_run())
