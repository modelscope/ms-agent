# Copyright (c) ModelScope Contributors. All rights reserved.
"""On-demand local codebase search via sirchmunk (replaces pre-turn RAG injection)."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.tools.search.sirchmunk_search import SirchmunkSearch, effective_localsearch_settings
from ms_agent.utils.logger import get_logger

logger = get_logger()

_SERVER = 'localsearch'
_TOOL = 'localsearch'

# Tool-facing description: aligned with sirchmunk AgenticSearch.search() capabilities.
_LOCALSEARCH_DESCRIPTION = """Search local files, codebases, and documents on disk.

USE THIS TOOL WHEN:
- The user asks about content in local files or directories
- You need to find information in source code, config files, or documents
- The query references a local path, project structure, or codebase
- You need to search PDF, DOCX, XLSX, PPTX, CSV, JSON, YAML, Markdown, etc.

DO NOT USE THIS TOOL WHEN:
- The user is asking a general knowledge question
- The user is greeting you or making casual conversation (e.g., "你好", "hello")
- You need information from the internet or recent events
- The query has no relation to local files or code

Returns:
Search results after summarizing as formatted text with file paths, code snippets, and explanations where
available. Retrieved excerpts and meta are included in the tool output.

Configured search roots for this agent (absolute paths; default search scope when `paths` is omitted):
{configured_roots}
"""


def _resolved_localsearch_paths_from_config(config) -> List[str]:
    """Match ``SirchmunkSearch`` path resolution for consistent tool text and checks."""
    block = effective_localsearch_settings(config)
    if not block:
        return []
    paths = block.get('paths', [])
    if isinstance(paths, str):
        paths = [paths]
    out: List[str] = []
    for p in paths or []:
        if p is None or not str(p).strip():
            continue
        out.append(str(Path(str(p).strip()).expanduser().resolve()))
    return out


def _format_configured_roots(paths: List[str]) -> str:
    if not paths:
        return '(none — set tools.localsearch.paths in agent config, or legacy knowledge_search.paths)'
    return '\n'.join(f'- {p}' for p in paths)


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _as_str_list(value: Any, name: str) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        return [value] if value.strip() else None
    if isinstance(value, list):
        out = [str(x).strip() for x in value if str(x).strip()]
        return out or None
    raise TypeError(f'{name} must be a string or list of strings')


class LocalSearchTool(ToolBase):
    """Expose sirchmunk as a callable tool when ``tools.localsearch`` is configured."""

    def __init__(self, config, **kwargs):
        super().__init__(config)
        tools_root = getattr(config, 'tools', None)
        tool_cfg = getattr(tools_root, 'localsearch', None) if tools_root else None
        if tool_cfg is not None:
            self.exclude_func(tool_cfg)
        self._searcher: Optional[SirchmunkSearch] = None
        self._configured_roots: List[str] = _resolved_localsearch_paths_from_config(config)

    def _tool_description(self) -> str:
        return _LOCALSEARCH_DESCRIPTION.format(configured_roots=_format_configured_roots(self._configured_roots))

    def _paths_param_description(self) -> str:
        roots = _format_configured_roots(self._configured_roots)
        return (
            'Optional. Narrow search to specific files or directories under the '
            'configured roots below. Each path must exist on disk and lie under '
            'one of these roots (or be exactly one of them).\n'
            f'Configured roots:\n{roots}'
        )

    def _ensure_searcher(self) -> SirchmunkSearch:
        if self._searcher is None:
            self._searcher = SirchmunkSearch(self.config)
        return self._searcher

    async def connect(self) -> None:
        return None

    async def _get_tools_inner(self) -> Dict[str, List[Tool]]:
        return {
            _SERVER: [
                Tool(
                    tool_name=_TOOL,
                    server_name=_SERVER,
                    description=self._tool_description(),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'query': {
                                'type': 'string',
                                'description': 'Search keywords or natural-language question about local content.',
                            },
                            'paths': {
                                'type': 'array',
                                'items': {'type': 'string'},
                                'description': self._paths_param_description(),
                            },
                            'mode': {
                                'type': 'string',
                                'enum': ['FAST', 'DEEP', 'FILENAME_ONLY'],
                                'description': 'Search mode; omit to use agent default (usually FAST).',
                            },
                            'max_depth': {
                                'type': 'integer',
                                'minimum': 1,
                                'maximum': 20,
                                'description': 'Max directory depth for filesystem search.',
                            },
                            'top_k_files': {
                                'type': 'integer',
                                'minimum': 1,
                                'maximum': 20,
                                'description': 'Max files for evidence / filename hits.',
                            },
                            'include': {
                                'type': 'array',
                                'items': {'type': 'string'},
                                'description': 'Glob patterns to include (e.g. *.py, *.md).',
                            },
                            'exclude': {
                                'type': 'array',
                                'items': {'type': 'string'},
                                'description': 'Glob patterns to exclude (e.g. *.pyc).',
                            },
                        },
                        'required': ['query'],
                    },
                )
            ]
        }

    async def call_tool(self, server_name: str, *, tool_name: str, tool_args: dict):
        del server_name
        if tool_name != _TOOL:
            return f'Unknown tool: {tool_name}'

        args = tool_args or {}
        query = str(args.get('query', '')).strip()
        if not query:
            return 'Error: `query` is required and cannot be empty.'

        try:
            paths_arg = _as_str_list(args.get('paths'), 'paths')
            mode = args.get('mode')
            if mode is not None:
                mode = str(mode).strip().upper() or None

            max_depth = args.get('max_depth')
            if max_depth is not None:
                max_depth = int(max_depth)
                max_depth = max(1, min(20, max_depth))

            top_k = args.get('top_k_files')
            if top_k is not None:
                top_k = int(top_k)
                top_k = max(1, min(20, top_k))

            include = _as_str_list(args.get('include'), 'include')
            exclude = _as_str_list(args.get('exclude'), 'exclude')

            searcher = self._ensure_searcher()
            resolved_paths = None
            if paths_arg:
                resolved_paths = searcher.resolve_tool_paths(paths_arg)
                if not resolved_paths:
                    roots = _format_configured_roots(self._configured_roots)
                    return (
                        'Error: `paths` are invalid. Each path must exist on disk and lie '
                        'under one of these configured roots:\n' + roots
                    )

            answer = await searcher.query(
                query,
                paths=resolved_paths,
                mode=mode,
                max_depth=max_depth,
                top_k_files=top_k,
                include=include,
                exclude=exclude,
            )
            details = searcher.get_search_details()
            excerpts = searcher.get_last_retrieved_chunks()

            lines = ['## Local search (sirchmunk)', '', str(answer), '']

            if excerpts:
                lines.append('## Retrieved excerpts')
                lines.append('')
                for i, item in enumerate(excerpts[:12], 1):
                    meta = item.get('metadata') or {}
                    src = meta.get('source', '?')
                    text = (item.get('text') or '')[:4000]
                    lines.append(f'### [{i}] {src}')
                    lines.append(text)
                    lines.append('')

            summary = {
                'mode': details.get('mode'),
                'paths': details.get('paths'),
                'work_path': details.get('work_path'),
                'cluster_cache_hit': details.get('cluster_cache_hit'),
            }
            lines.append('## Meta')
            lines.append(_json_dumps(summary))

            full_text = '\n'.join(lines)
            # Model sees answer + source paths only; UI gets full excerpts + meta.
            result_parts = [str(answer).strip()]
            if excerpts:
                result_parts.append('\nSource paths:')
                for item in excerpts[:12]:
                    meta = item.get('metadata') or {}
                    result_parts.append(f'- {meta.get("source", "?")}')
            result_text = '\n'.join(result_parts)

            return {
                'result': result_text,
                'tool_detail': full_text,
            }
        except (TypeError, ValueError) as exc:
            return f'Invalid tool arguments: {exc}'
        except Exception as exc:
            logger.warning(f'localsearch failed: {exc}')
            return f'Local search failed: {exc}'
