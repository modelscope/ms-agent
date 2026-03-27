# Copyright (c) ModelScope Contributors. All rights reserved.
"""On-demand local codebase search via sirchmunk (replaces pre-turn RAG injection)."""

import asyncio
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.tools.search.localsearch_catalog import (
    build_file_catalog_text, catalog_cache_path, catalog_fingerprint,
    description_catalog_settings, load_cached_catalog, save_cached_catalog)
from ms_agent.tools.search.sirchmunk_search import (
    SirchmunkSearch, effective_localsearch_settings)
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
- Large files or directories should be searched by this tool.


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

{file_catalog_section}
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


def _work_path_from_config(config) -> Path:
    block = effective_localsearch_settings(config)
    if not block:
        return Path('.sirchmunk').expanduser().resolve()
    wp = block.get('work_path', './.sirchmunk') if hasattr(
        block, 'get') else getattr(block, 'work_path', './.sirchmunk')
    return Path(str(wp)).expanduser().resolve()


def _truncate_catalog_text(text: str, max_chars: int) -> str:
    """Truncate catalog text to ``max_chars``, preserving the directory tree section
    and truncating the file-summary section on entry boundaries.

    The catalog has two sections:
      1. Directory structure (``#### Directory structure of ...``)
      2. File summaries (``#### File summaries ...``) — entries start with ``- ``

    Strategy: always keep the full directory tree (it fits in a few hundred chars
    per root); truncate only the file-summary entries within the remaining budget.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    import re

    # Locate the first file-summary section header.
    summary_header_m = re.search(r'^#### File summaries', text, re.MULTILINE)
    if summary_header_m is None:
        # No file summaries — just hard-truncate.
        return text[:max_chars - 24].rstrip() + '\n\n… (truncated)'

    # Everything up to and including the file-summary header line is the
    # "prefix" we always keep.
    header_section_end = text.find('\n', summary_header_m.end())
    if header_section_end == -1:
        return text[:max_chars - 24].rstrip() + '\n\n… (truncated)'

    prefix = text[:header_section_end + 1]
    body = text[header_section_end + 1:]

    # Split body into individual entry lines (each starts with "- ").
    parts = re.split(r'(?=^- )', body, flags=re.MULTILINE)
    parts = [p for p in parts if p.strip()]

    budget = max_chars - len(prefix) - 50  # reserve space for trailing note
    kept: list[str] = []
    used = 0
    for part in parts:
        if used + len(part) > budget:
            break
        kept.append(part)
        used += len(part)

    omitted = len(parts) - len(kept)
    suffix = f'\n… ({omitted} more files not shown)' if omitted > 0 else ''
    return prefix + ''.join(kept).rstrip() + suffix


def _format_configured_roots(paths: List[str]) -> str:
    if not paths:
        return ('(none — set tools.localsearch.paths in agent config, '
                'or legacy knowledge_search.paths)')
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
        tool_cfg = getattr(tools_root, 'localsearch',
                           None) if tools_root else None
        if tool_cfg is not None:
            self.exclude_func(tool_cfg)
        self._searcher: Optional[SirchmunkSearch] = None
        self._configured_roots: List[str] = (
            _resolved_localsearch_paths_from_config(config))
        block = effective_localsearch_settings(config)
        self._catalog_enabled, self._catalog_opts = description_catalog_settings(
            block)
        self._work_path = _work_path_from_config(config)
        self._catalog_text: str = ''
        self._catalog_build_error: Optional[str] = None

    def _file_catalog_section(self) -> str:
        if not self._catalog_enabled:
            return ''
        err = self._catalog_build_error
        if err:
            return ('\n\n## Local knowledge catalog\n'
                    f'_(Catalog build failed: {err})_\n')
        body = (self._catalog_text or '').strip()
        if not body:
            return ('\n\n## Local knowledge catalog\n'
                    '_(No scannable files or catalog empty.)_\n')
        shown = _truncate_catalog_text(body, self._catalog_opts['max_chars'])
        return (
            '\n\n## Local knowledge catalog (shallow scan)\n'
            'Brief previews of files under the configured roots; call this tool '
            'with a `query` for full search.\n\n' + shown + '\n')

    def _tool_description(self) -> str:
        return _LOCALSEARCH_DESCRIPTION.format(
            configured_roots=_format_configured_roots(self._configured_roots),
            file_catalog_section=self._file_catalog_section())

    def _paths_param_description(self) -> str:
        roots = _format_configured_roots(self._configured_roots)
        return (
            'Optional. Narrow search to specific files or directories under the '
            'configured roots below. Each path must exist on disk and lie under '
            'one of these roots (or be exactly one of them).\n'
            f'Configured roots:\n{roots}')

    def _ensure_searcher(self) -> SirchmunkSearch:
        if self._searcher is None:
            self._searcher = SirchmunkSearch(self.config)
        return self._searcher

    async def connect(self) -> None:
        self._catalog_build_error = None
        self._catalog_text = ''
        if not self._catalog_enabled:
            return
        roots = [r for r in self._configured_roots if r]
        if not roots:
            self._catalog_build_error = 'no configured roots'
            return
        o = self._catalog_opts
        fp = catalog_fingerprint(
            roots,
            o['max_files'],
            o['max_depth'],
            o['max_preview_chars'],
            o['max_chars'],
            o['exclude_extra'],
        )
        cache_path = catalog_cache_path(self._work_path, fp)
        ttl = float(o['cache_ttl_seconds'])
        t0 = time.monotonic()
        cached = load_cached_catalog(cache_path, ttl)
        if cached is not None:
            elapsed = time.monotonic() - t0
            self._catalog_text = cached
            logger.info(
                f'localsearch catalog: loaded from cache in {elapsed:.3f}s '
                f'({len(cached)} chars) roots={roots}')
            return
        try:
            built = await build_file_catalog_text(
                roots,
                max_files=o['max_files'],
                max_depth=o['max_depth'],
                max_preview_chars=o['max_preview_chars'],
                exclude_extra=o['exclude_extra'],
                max_file_size_mb=o['max_file_size_mb'],
                oversized_pdf_timeout_s=o['oversized_pdf_timeout_s'],
                max_chars=o['max_chars'],
            )
            elapsed = time.monotonic() - t0
            self._catalog_text = built
            logger.info(f'localsearch catalog: scanned in {elapsed:.3f}s '
                        f'({len(built)} chars) roots={roots}')
            if ttl > 0 and built.strip():
                try:
                    save_cached_catalog(cache_path, built)
                except OSError as exc:
                    logger.debug(
                        f'localsearch catalog cache write failed: {exc}')
        except ImportError as exc:
            elapsed = time.monotonic() - t0
            self._catalog_build_error = str(exc)
            logger.warning(
                f'localsearch description_catalog ({elapsed:.3f}s): {exc}')
        except Exception as exc:
            elapsed = time.monotonic() - t0
            self._catalog_build_error = str(exc)
            logger.warning(
                f'localsearch description_catalog scan failed ({elapsed:.3f}s): {exc}'
            )

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
                                'type':
                                'string',
                                'description':
                                'Search keywords or natural-language question about local content.',
                            },
                            'paths': {
                                'type': 'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description': self._paths_param_description(),
                            },
                            'mode': {
                                'type':
                                'string',
                                'enum': ['FAST', 'DEEP', 'FILENAME_ONLY'],
                                'description':
                                'Search mode; omit to use agent default (usually FAST).',
                            },
                            'max_depth': {
                                'type':
                                'integer',
                                'minimum':
                                1,
                                'maximum':
                                20,
                                'description':
                                'Max directory depth for filesystem search.',
                            },
                            'top_k_files': {
                                'type':
                                'integer',
                                'minimum':
                                1,
                                'maximum':
                                20,
                                'description':
                                'Max files for evidence / filename hits.',
                            },
                            'include': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                'Glob patterns to include (e.g. *.py, *.md).',
                            },
                            'exclude': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                'Glob patterns to exclude (e.g. *.pyc).',
                            },
                        },
                        'required': ['query'],
                    },
                )
            ]
        }

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict):
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
                        'under one of these configured roots:\n' + roots)

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

    async def call_tool_streaming(self, server_name: str, *, tool_name: str,
                                  tool_args: dict):
        """Streaming variant: yield log lines while searching, then yield final result.

        Intermediate yields are plain strings (log lines).
        The final yield is the result dict (or error string) from call_tool.

        Timeout semantics: the caller should treat the absence of any yield
        within 30 s as a hang and cancel the task.
        """
        log_queue: asyncio.Queue = asyncio.Queue()

        # Register the streaming callback on the searcher so sirchmunk pushes
        # log lines into our queue as they are emitted.
        async def _on_log(entry: str):
            await log_queue.put(entry)

        # We need the searcher to exist before we can register the callback.
        # _ensure_searcher() is synchronous and cheap if already initialized.
        try:
            searcher = self._ensure_searcher()
            searcher.enable_streaming_logs(_on_log)
        except Exception as exc:
            yield f'Local search failed: {exc}'
            return

        # Sentinel placed in the queue by the search coroutine when done.
        _DONE = object()

        async def _run_search():
            try:
                result = await self.call_tool(
                    server_name, tool_name=tool_name, tool_args=tool_args)
            except Exception as exc:
                result = f'Local search failed: {exc}'
            await log_queue.put(_DONE)
            await log_queue.put(result)

        search_task = asyncio.create_task(_run_search())

        try:
            while True:
                item = await log_queue.get()
                if item is _DONE:
                    # Next item is the final result.
                    final = await log_queue.get()
                    yield final
                    break
                # Intermediate log line.
                yield item
        finally:
            search_task.cancel()
            try:
                await search_task
            except asyncio.CancelledError:
                pass
