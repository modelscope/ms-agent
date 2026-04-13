# Copyright (c) ModelScope Contributors. All rights reserved.
"""Read-only workspace search: grep (rg or Python fallback) and glob."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.artifact_manager import ArtifactManager
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR
from ms_agent.utils.workspace_policy import WorkspacePolicyError, WorkspacePolicyKernel

logger = get_logger()

_TEXT_SUFFIXES = {
    '.py', '.md', '.txt', '.yaml', '.yml', '.json', '.toml', '.cfg', '.ini',
    '.sh', '.bash', '.js', '.ts', '.tsx', '.jsx', '.css', '.html', '.xml',
    '.rs', '.go', '.java', '.c', '.h', '.cpp', '.hpp', '.cs', '.rb', '.php',
    '.sql', '.vue', '.svelte', '.m', '.swift', '.kt', '.gradle', '.properties',
    '.env', '.gitignore', '.dockerignore', 'Dockerfile',
}


class WorkspaceSearchTool(ToolBase):
    """Grep and glob under output_dir (+ optional extra roots) with shared policy."""

    def __init__(self, config, **kwargs):
        super().__init__(config)
        self.output_dir = Path(
            getattr(config, 'output_dir', DEFAULT_OUTPUT_DIR)).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        wp = getattr(getattr(config, 'tools', None), 'workspace_policy', None)
        extra = []
        deny: list[str] = []
        if wp is not None:
            extra = list(getattr(wp, 'allow_roots', []) or [])
            deny = list(getattr(wp, 'deny_globs', []) or [])
        else:
            deny = []
        ws = getattr(getattr(config, 'tools', None), 'workspace_search', None)
        self._default_head = int(getattr(ws, 'default_head_limit', 250) or 250)
        self._glob_max = int(getattr(ws, 'max_files', 100) or 100)
        self._grep_timeout = int(getattr(ws, 'grep_timeout_s', 120) or 120)

        shell_cfg = getattr(
            getattr(config.tools, 'code_executor', None), 'shell', None)
        shell_mode = getattr(shell_cfg, 'default_mode',
                             'workspace_write') if shell_cfg else 'workspace_write'
        net = bool(getattr(shell_cfg, 'network_enabled', False)
                   ) if shell_cfg else False
        max_cmd = int(getattr(shell_cfg, 'max_command_chars', 8192)
                      ) if shell_cfg else 8192

        self._policy = WorkspacePolicyKernel(
            self.output_dir,
            extra_allow_roots=extra,
            deny_globs=deny if deny else None,
            shell_default_mode=str(shell_mode),
            shell_network_enabled=net,
            max_command_chars=max_cmd,
        )
        max_kb = 256
        if shell_cfg and getattr(shell_cfg, 'max_output_kb', None):
            max_kb = int(shell_cfg.max_output_kb)
        self._artifacts = ArtifactManager(
            self.output_dir, max_combined_bytes=max_kb * 1024)

        self.exclude_func(ws)

    async def connect(self) -> None:
        return

    async def _get_tools_inner(self) -> Dict[str, Any]:
        return {
            'workspace_search': [
                Tool(
                    tool_name='grep_files',
                    server_name='workspace_search',
                    description=(
                        'Search file contents under the workspace using ripgrep when available, '
                        'otherwise a safe Python scan. Paths must stay under the configured output/workspace roots. '
                        'Read-only.'
                    ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'pattern': {
                                'type': 'string',
                                'description': 'Regular expression (Rust regex if rg is used).',
                            },
                            'path': {
                                'type': 'string',
                                'description':
                                'Directory or file to search (relative to output_dir if not absolute). Default ".".',
                            },
                            'glob': {
                                'type': 'string',
                                'description': 'Optional glob filter for files, e.g. "*.py"',
                            },
                            'output_mode': {
                                'type': 'string',
                                'enum': ['content', 'files_with_matches', 'count'],
                                'description': 'content: matching lines; files_with_matches: paths only; count: per-file counts',
                            },
                            'head_limit': {
                                'type': 'integer',
                                'description': 'Max lines (content) or paths/count entries to return',
                            },
                            'offset': {
                                'type': 'integer',
                                'description': 'Skip first N lines/entries after collect',
                            },
                            'case_insensitive': {
                                'type': 'boolean',
                                'description': 'Case-insensitive search',
                            },
                        },
                        'required': ['pattern'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='glob_files',
                    server_name='workspace_search',
                    description=(
                        'List files under a workspace directory matching a glob pattern '
                        '(e.g. "**/*.py", "*.md"). Read-only; results are capped.'
                    ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'pattern': {
                                'type': 'string',
                                'description': 'Glob pattern relative to path',
                            },
                            'path': {
                                'type': 'string',
                                'description': 'Base directory (relative to output_dir if not absolute).',
                            },
                        },
                        'required': ['pattern'],
                        'additionalProperties': False,
                    },
                ),
            ]
        }

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await getattr(self, tool_name)(**tool_args)

    async def grep_files(
        self,
        pattern: str,
        path: str = '.',
        glob: Optional[str] = None,
        output_mode: str = 'files_with_matches',
        head_limit: Optional[int] = None,
        offset: Optional[int] = None,
        case_insensitive: bool = False,
    ) -> str:
        call_id = f'grep-{pattern[:40]}'
        head_limit = head_limit if head_limit is not None else self._default_head
        offset = offset or 0
        path = path or '.'
        try:
            root = self._policy.resolve_under_roots(path)
        except WorkspacePolicyError as e:
            return json.dumps({'success': False, 'error': str(e)}, indent=2)

        lines: List[str] = []
        try:
            rg = shutil.which('rg')
            if rg and root.is_file():
                lines = await self._rg_file(rg, pattern, root, case_insensitive,
                                            output_mode, head_limit, offset,
                                            glob)
            elif rg and root.is_dir():
                lines = await self._rg_dir(rg, pattern, root, case_insensitive,
                                           output_mode, head_limit, offset,
                                           glob)
            else:
                lines = self._python_grep(
                    pattern,
                    root,
                    glob,
                    output_mode,
                    head_limit,
                    offset,
                    case_insensitive,
                )
        except Exception as e:
            logger.warning('grep_files failed: %s', e, exc_info=True)
            return json.dumps({'success': False, 'error': str(e)}, indent=2)

        text = '\n'.join(lines)
        packed = self._artifacts.pack_text_result(
            tool_name='grep_files',
            call_id=call_id,
            stdout=text,
            stderr='',
            extra={
                'success': True,
                'output_mode': output_mode,
                'num_lines': len(lines),
            },
        )
        return json.dumps(packed, ensure_ascii=False, indent=2, default=str)

    async def _rg_file(
        self,
        rg: str,
        pattern: str,
        file_path: Path,
        case_insensitive: bool,
        output_mode: str,
        head_limit: int,
        offset: int,
        glob: Optional[str],
    ) -> List[str]:
        args = [rg, '--no-heading', '--color', 'never']
        if case_insensitive:
            args.append('-i')
        if glob:
            args.extend(['--glob', glob])
        if output_mode == 'files_with_matches':
            args.extend(['-l', pattern, str(file_path)])
        elif output_mode == 'count':
            args.extend(['-c', pattern, str(file_path)])
        else:
            args.extend(['-n', pattern, str(file_path)])
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._policy.workspace_root),
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(),
                                              timeout=self._grep_timeout)
        out = (out_b or b'').decode('utf-8', errors='replace').strip('\n')
        err = (err_b or b'').decode('utf-8', errors='replace').strip('\n')
        if proc.returncode not in (0, 1):
            raise RuntimeError(err or f'rg exited {proc.returncode}')
        lines = [ln for ln in out.split('\n') if ln] if out else []
        return _apply_offset_limit(lines, offset, head_limit)

    async def _rg_dir(
        self,
        rg: str,
        pattern: str,
        root: Path,
        case_insensitive: bool,
        output_mode: str,
        head_limit: int,
        offset: int,
        glob: Optional[str],
    ) -> List[str]:
        args = [rg, '--no-heading', '--color', 'never']
        if case_insensitive:
            args.append('-i')
        if glob:
            args.extend(['--glob', glob])
        if output_mode == 'files_with_matches':
            args.extend(['-l', pattern, str(root)])
        elif output_mode == 'count':
            args.extend(['--count-matches', pattern, str(root)])
        else:
            args.extend(['-n', pattern, str(root)])
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._policy.workspace_root),
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(),
                                              timeout=self._grep_timeout)
        out = (out_b or b'').decode('utf-8', errors='replace').strip('\n')
        err = (err_b or b'').decode('utf-8', errors='replace').strip('\n')
        if proc.returncode not in (0, 1):
            raise RuntimeError(err or f'rg exited {proc.returncode}')
        lines = [ln for ln in out.split('\n') if ln] if out else []
        return _apply_offset_limit(lines, offset, head_limit)

    def _python_grep(
        self,
        pattern: str,
        root: Path,
        glob_pat: Optional[str],
        output_mode: str,
        head_limit: int,
        offset: int,
        case_insensitive: bool,
    ) -> List[str]:
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            return [f'[error] invalid regex: {e}']
        lines_out: List[str] = []
        counts: Dict[str, int] = {}

        def consider_file(fp: Path) -> bool:
            if glob_pat:
                rel = str(fp.relative_to(root)) if root.is_dir() else fp.name
                if not fnmatch.fnmatch(fp.name, glob_pat) and not fnmatch.fnmatch(
                        rel, glob_pat):
                    return False
            suf = fp.suffix.lower()
            if suf not in _TEXT_SUFFIXES and fp.suffix == '':
                if fp.name not in ('Dockerfile', 'Makefile', 'README'):
                    return False
            return fp.is_file()

        files: List[Path] = []
        if root.is_file():
            files = [root]
        else:
            for fp in _walk_files_limited(root, self._policy.deny_globs, 50_000):
                if consider_file(fp):
                    files.append(fp)

        for fp in files:
            try:
                text = fp.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            rel = str(fp.relative_to(self._policy.workspace_root)) if _is_relative(
                fp, self._policy.workspace_root) else str(fp)
            if output_mode == 'files_with_matches':
                if rx.search(text):
                    lines_out.append(rel)
            elif output_mode == 'count':
                n = len(rx.findall(text))
                if n:
                    counts[rel] = n
            else:
                for i, line in enumerate(text.splitlines(), start=1):
                    if rx.search(line):
                        lines_out.append(f'{rel}:{i}:{line}')
            if len(lines_out) >= head_limit + offset + 5000:
                break

        if output_mode == 'count':
            lines_out = [f'{k}:{v}' for k, v in sorted(counts.items())]
        return _apply_offset_limit(lines_out, offset, head_limit)

    async def glob_files(self, pattern: str, path: str = '') -> str:
        call_id = f'glob-{pattern[:40]}'
        try:
            base = self._policy.resolve_under_roots(path or '.')
        except WorkspacePolicyError as e:
            return json.dumps({'success': False, 'error': str(e)}, indent=2)

        if not base.is_dir():
            return json.dumps(
                {
                    'success': False,
                    'error': f'Not a directory: {path}',
                },
                indent=2,
            )

        matches: List[str] = []
        truncated = False
        deny = self._policy.deny_globs

        # Prefer pathlib.glob from base
        try:
            for p in sorted(base.glob(pattern)):
                if not p.is_file():
                    continue
                rp = p.resolve()
                if not self._policy.path_is_allowed(rp):
                    continue
                if _is_denied_path(rp, base, deny):
                    continue
                rel = str(p.relative_to(self._policy.workspace_root)) if _is_relative(
                    p, self._policy.workspace_root) else str(p)
                matches.append(rel)
                if len(matches) >= self._glob_max:
                    truncated = True
                    break
        except ValueError:
            # invalid pattern
            return json.dumps(
                {
                    'success': False,
                    'error': 'Invalid glob pattern',
                },
                indent=2,
            )

        text = json.dumps(
            {
                'success': True,
                'num_files': len(matches),
                'filenames': matches,
                'truncated': truncated,
            },
            ensure_ascii=False,
            indent=2,
        )
        packed = self._artifacts.pack_text_result(
            tool_name='glob_files',
            call_id=call_id,
            stdout=text,
            stderr='',
            extra={'success': True},
        )
        return json.dumps(packed, ensure_ascii=False, indent=2, default=str)


def _apply_offset_limit(lines: List[str], offset: int,
                        head_limit: int) -> List[str]:
    if offset:
        lines = lines[offset:]
    if head_limit and head_limit > 0:
        lines = lines[:head_limit]
    return lines


def _is_relative(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _is_denied_path(path: Path, root: Path, deny: tuple[str, ...]) -> bool:
    if not deny:
        return False
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    for pat in deny:
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


def _walk_files_limited(root: Path, deny: tuple[str, ...],
                        max_files: int) -> List[Path]:
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(
            root, topdown=True, followlinks=False):
        dp = Path(dirpath)
        pruned = []
        for d in list(dirnames):
            child = dp / d
            try:
                rel = child.relative_to(root).as_posix()
            except ValueError:
                rel = child.as_posix()
            skip = any(fnmatch.fnmatch(rel, p) for p in deny)
            if skip:
                continue
            pruned.append(d)
        dirnames[:] = pruned
        for name in filenames:
            out.append(dp / name)
            if len(out) >= max_files:
                return out
    return out
