# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import base64
import fnmatch
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

from ms_agent.llm import LLM
from ms_agent.llm.utils import Message, Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.artifact_manager import ArtifactManager
from ms_agent.utils.constants import DEFAULT_INDEX_DIR, DEFAULT_OUTPUT_DIR
from ms_agent.utils.workspace_policy import WorkspacePolicyError, WorkspacePolicyKernel

logger = get_logger()

_FS_TOOL_ALIASES = {'read': 'read_file', 'edit': 'edit_file', 'write': 'write_file'}

_TEXT_SUFFIXES = {
    '.py', '.md', '.txt', '.yaml', '.yml', '.json', '.toml', '.cfg', '.ini',
    '.sh', '.bash', '.js', '.ts', '.tsx', '.jsx', '.css', '.html', '.xml',
    '.rs', '.go', '.java', '.c', '.h', '.cpp', '.hpp', '.cs', '.rb', '.php',
    '.sql', '.vue', '.svelte', '.m', '.swift', '.kt', '.gradle', '.properties',
    '.env', '.gitignore', '.dockerignore', 'Dockerfile',
}


class FileSystemTool(ToolBase):
    """A file system operation tool"""

    MAX_READ_BYTES = 10 * 1024 * 1024  # 10 MB per file
    IMAGE_EXTENSIONS = frozenset({'png', 'jpg', 'jpeg', 'gif', 'webp'})
    # Curly quote → straight quote mapping for fuzzy matching
    CURLY_QUOTE_MAP = {
        '\u2018': "'", '\u2019': "'",  # ' '
        '\u201c': '"', '\u201d': '"',  # " "
    }

    SYSTEM_FOR_ABBREVIATIONS = """你是一个帮我简化文件信息并返回缩略的机器人，你需要根据输入文件内容来生成压缩过的文件内容。

要求：
1. 如果是代码文件，你需要保留imports、exports、类信息、方法信息、异步或同步等可用于其他文件引用或理解的必要信息
2. 如果是配置文件，你需要保留所有的key
3. 如果是文档，你需要总结所有章节，并给出一个精简的版本

你的返回内容会直接存储下来，因此你需要省略其他非必要符号，例如"```"或者"让我来帮忙..."都不需要。

你的优化目标：
1. 【优先】保留充足的信息，尽量不损失原意
2. 【其次】保留尽量少的token数量
"""

    def __init__(self, config, **kwargs):
        super().__init__(config)
        self.exclude_func(getattr(config.tools, 'file_system', None))
        if self.include_functions:
            self.include_functions = [
                _FS_TOOL_ALIASES.get(n, n) for n in self.include_functions
            ]
        if self.exclude_functions:
            self.exclude_functions = [
                _FS_TOOL_ALIASES.get(n, n) for n in self.exclude_functions
            ]
        self.output_dir = getattr(config, 'output_dir', DEFAULT_OUTPUT_DIR)
        self.trust_remote_code = kwargs.get('trust_remote_code', False)
        self.allow_read_all_files = getattr(
            getattr(config.tools, 'file_system', {}), 'allow_read_all_files',
            False)
        if not self.trust_remote_code:
            self.allow_read_all_files = False
        if hasattr(self.config, 'llm'):
            self.llm: LLM = LLM.from_config(self.config)
        index_dir = getattr(config, 'index_cache_dir', DEFAULT_INDEX_DIR)
        self.index_dir = os.path.join(self.output_dir, index_dir)
        self.system = self.SYSTEM_FOR_ABBREVIATIONS
        if hasattr(self.config.tools.file_system, 'system_for_abbreviations'):
            self.system = self.config.tools.file_system.system_for_abbreviations
        # read_file dedup only: {real_path: {"mtime", "offset", "limit"}}
        self._read_cache: dict[str, dict] = {}

        fs_cfg = getattr(config.tools, 'file_system', None)
        self._grep_timeout = int(getattr(fs_cfg, 'grep_timeout_s', 120) or 120)
        self._default_grep_head = int(
            getattr(fs_cfg, 'grep_head_limit', 250) or 250)
        self._glob_max_files = int(getattr(fs_cfg, 'glob_max_files', 100) or 100)

        wp = getattr(getattr(config, 'tools', None), 'workspace_policy', None)
        extra = list(getattr(wp, 'allow_roots', []) or []) if wp else []
        deny = list(getattr(wp, 'deny_globs', []) or []) if wp else []

        shell_cfg = getattr(
            getattr(config.tools, 'code_executor', None), 'shell', None)
        shell_mode = getattr(shell_cfg, 'default_mode',
                             'workspace_write') if shell_cfg else 'workspace_write'
        net = bool(getattr(shell_cfg, 'network_enabled', False)
                   ) if shell_cfg else False
        max_cmd = int(getattr(shell_cfg, 'max_command_chars', 8192)
                      ) if shell_cfg else 8192

        _out_p = Path(self.output_dir).expanduser().resolve()
        try:
            _out_p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._fs_policy = WorkspacePolicyKernel(
            _out_p,
            extra_allow_roots=extra,
            deny_globs=deny if deny else None,
            shell_default_mode=str(shell_mode),
            shell_network_enabled=net,
            max_command_chars=max_cmd,
        )
        max_kb = 256
        if shell_cfg and getattr(shell_cfg, 'max_output_kb', None):
            max_kb = int(shell_cfg.max_output_kb)
        self._fs_artifacts = ArtifactManager(
            _out_p, max_combined_bytes=max_kb * 1024)

    async def connect(self):
        logger.warning_once(
            '[IMPORTANT]FileSystemTool is not implemented with sandbox, please consider other similar '
            'tools if you want to run dangerous code.')

    async def _get_tools_inner(self):
        tools = {
            'file_system': [
                Tool(
                    tool_name='write_file',
                    server_name='file_system',
                    description=(
                        'Write content to a file. Creates the file if it does not exist, '
                        'or overwrites it if it does.\n\n'
                        'Usage:\n'
                        '- Prefer `edit_file` for modifying existing files — it only changes the relevant section.\n'
                        '- Use this tool to create new files or perform a complete rewrite.\n'
                        '- Parent directories are created automatically if they do not exist.\n\n'
                        'No prior `read_file` is required; the path is resolved and the given `content` is written as-is.'
                    ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type': 'string',
                                'description': 'The relative path of the file to write',
                            },
                            'content': {
                                'type': 'string',
                                'description': 'The full content to write into the file',
                            },
                        },
                        'required': ['path', 'content'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='read_file',
                    server_name='file_system',
                    description=(
                        'Read the content of one or more files.\n\n'
                        '- `paths`: list of relative file paths to read.\n'
                        '- For image files (png/jpg/jpeg/gif/webp), returns base64-encoded content.\n'
                        '- `offset`: line number to start reading from (1-based). '
                        'Only effective when paths has exactly one element. Omit to read from the beginning.\n'
                        '- `limit`: number of lines to read. '
                        'Only effective when paths has exactly one element. Omit to read to the end.\n'
                        '- `abbreviate`: if true, use an LLM to return a condensed summary of each file '
                        'instead of the raw content. Cached after first call. '
                        'Use this for a quick structural overview; read the full file if more detail is needed.'
                    ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'paths': {
                                'type': 'array',
                                'items': {'type': 'string'},
                                'description':
                                'List of relative file path(s) to read',
                            },
                            'offset': {
                                'type': 'integer',
                                'description':
                                'Line number to start reading from (1-based). '
                                'Only provide if the file is too large to read at once.',
                            },
                            'limit': {
                                'type': 'integer',
                                'description':
                                'Number of lines to read. '
                                'Only provide if the file is too large to read at once.',
                            },
                            'abbreviate': {
                                'type': 'boolean',
                                'description':
                                'If true, return an LLM-generated summary instead of raw content. '
                                'Useful for large files or quick structural overview.',
                            },
                        },
                        'required': ['paths'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='edit_file',
                    server_name='file_system',
                    description=(
                        'Edit an existing file by replacing an exact string with new content.\n\n'
                        'The tool reads the file from disk and checks that `old_string` appears in the current '
                        'contents before applying the edit — you do not need a prior `read_file` call for '
                        'staleness. Still use `read_file` or `grep` when you need the exact snippet in the '
                        'conversation so you can form a correct `old_string`.\n\n'
                        'You must provide the exact text to find (`old_string`) and the replacement (`new_string`).\n'
                        '`old_string` must match the file content EXACTLY — including whitespace and line breaks.\n'
                        'If `old_string` appears multiple times and `replace_all` is false, the call will fail '
                        'with the match count so you can add more context to make it unique.\n\n'
                        'Special case — `old_string=""`:\n'
                        '- File does not exist: creates the file with `new_string` as its content.\n'
                        '- File exists and is empty: fills it with `new_string`.\n'
                        '- File exists and has content: returns an error. Use `write_file` for a full rewrite.'
                    ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type': 'string',
                                'description': 'The relative path of the file to edit.',
                            },
                            'old_string': {
                                'type': 'string',
                                'description': 'The exact string to find and replace.',
                            },
                            'new_string': {
                                'type': 'string',
                                'description': 'The string to replace it with.',
                            },
                            'replace_all': {
                                'type': 'boolean',
                                'description':
                                'If true, replace all occurrences. Default is false (replace only the first).',
                            },
                        },
                        'required': ['path', 'old_string', 'new_string'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='grep',
                    server_name='file_system',
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
                                'description':
                                'content: matching lines; files_with_matches: paths only; count: per-file counts',
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
                    tool_name='glob',
                    server_name='file_system',
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
                                'description':
                                'Base directory (relative to output_dir if not absolute).',
                            },
                        },
                        'required': ['pattern'],
                        'additionalProperties': False,
                    },
                ),

            ]
        }
        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await getattr(self, tool_name)(**tool_args)

    async def grep(
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
        head_limit = (head_limit if head_limit is not None else
                      self._default_grep_head)
        offset = offset or 0
        path = path or '.'
        try:
            root = self._fs_policy.resolve_under_roots(path)
        except WorkspacePolicyError as e:
            return json.dumps({'success': False, 'error': str(e)}, indent=2)

        lines: List[str] = []
        try:
            rg = shutil.which('rg')
            if rg and root.is_file():
                lines = await self._grep_rg_file(rg, pattern, root,
                                                 case_insensitive, output_mode,
                                                 head_limit, offset, glob)
            elif rg and root.is_dir():
                lines = await self._grep_rg_dir(rg, pattern, root,
                                                case_insensitive, output_mode,
                                                head_limit, offset, glob)
            else:
                lines = self._grep_python(
                    pattern,
                    root,
                    glob,
                    output_mode,
                    head_limit,
                    offset,
                    case_insensitive,
                )
        except Exception as e:
            logger.warning('grep failed: %s', e, exc_info=True)
            return json.dumps({'success': False, 'error': str(e)}, indent=2)

        text = '\n'.join(lines)
        packed = self._fs_artifacts.pack_text_result(
            tool_name='grep',
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

    async def _grep_rg_file(
        self,
        rg: str,
        pattern: str,
        file_path: Path,
        case_insensitive: bool,
        output_mode: str,
        head_limit: int,
        offset: int,
        glob_pat: Optional[str],
    ) -> List[str]:
        args = [rg, '--no-heading', '--color', 'never']
        if case_insensitive:
            args.append('-i')
        if glob_pat:
            args.extend(['--glob', glob_pat])
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
            cwd=str(self._fs_policy.workspace_root),
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(),
                                              timeout=self._grep_timeout)
        out = (out_b or b'').decode('utf-8', errors='replace').strip('\n')
        err = (err_b or b'').decode('utf-8', errors='replace').strip('\n')
        if proc.returncode not in (0, 1):
            raise RuntimeError(err or f'rg exited {proc.returncode}')
        lines = [ln for ln in out.split('\n') if ln] if out else []
        return _apply_offset_limit(lines, offset, head_limit)

    async def _grep_rg_dir(
        self,
        rg: str,
        pattern: str,
        root: Path,
        case_insensitive: bool,
        output_mode: str,
        head_limit: int,
        offset: int,
        glob_pat: Optional[str],
    ) -> List[str]:
        args = [rg, '--no-heading', '--color', 'never']
        if case_insensitive:
            args.append('-i')
        if glob_pat:
            args.extend(['--glob', glob_pat])
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
            cwd=str(self._fs_policy.workspace_root),
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(),
                                              timeout=self._grep_timeout)
        out = (out_b or b'').decode('utf-8', errors='replace').strip('\n')
        err = (err_b or b'').decode('utf-8', errors='replace').strip('\n')
        if proc.returncode not in (0, 1):
            raise RuntimeError(err or f'rg exited {proc.returncode}')
        lines = [ln for ln in out.split('\n') if ln] if out else []
        return _apply_offset_limit(lines, offset, head_limit)

    def _grep_python(
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
            for fp in _walk_files_limited(root, self._fs_policy.deny_globs,
                                          50_000):
                if consider_file(fp):
                    files.append(fp)

        for fp in files:
            try:
                text = fp.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            rel = str(fp.relative_to(self._fs_policy.workspace_root)
                      ) if _is_relative(fp, self._fs_policy.workspace_root) else str(
                          fp)
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

    async def glob(self, pattern: str, path: str = '') -> str:
        call_id = f'glob-{pattern[:40]}'
        try:
            base = self._fs_policy.resolve_under_roots(path or '.')
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
        deny = self._fs_policy.deny_globs

        try:
            for p in sorted(base.glob(pattern)):
                if not p.is_file():
                    continue
                rp = p.resolve()
                if not self._fs_policy.path_is_allowed(rp):
                    continue
                if _is_denied_path(rp, base, deny):
                    continue
                rel = str(p.relative_to(self._fs_policy.workspace_root)
                          ) if _is_relative(p, self._fs_policy.workspace_root
                                            ) else str(p)
                matches.append(rel)
                if len(matches) >= self._glob_max_files:
                    truncated = True
                    break
        except ValueError:
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
        packed = self._fs_artifacts.pack_text_result(
            tool_name='glob',
            call_id=call_id,
            stdout=text,
            stderr='',
            extra={'success': True},
        )
        return json.dumps(packed, ensure_ascii=False, indent=2, default=str)

    def _normalize_quotes(self, s: str) -> str:
        for curly, straight in self.CURLY_QUOTE_MAP.items():
            s = s.replace(curly, straight)
        return s

    def _preserve_quote_style(self, old_string: str, actual_old: str, new_string: str) -> str:
        """If old_string matched via quote normalization, apply the same curly quotes to new_string."""
        if old_string == actual_old:
            return new_string
        has_double = any(c in actual_old for c in '\u201c\u201d')
        has_single = any(c in actual_old for c in '\u2018\u2019')
        result = new_string
        if has_double:
            out, chars = [], list(result)
            for i, ch in enumerate(chars):
                if ch == '"':
                    prev = chars[i - 1] if i > 0 else None
                    opening = prev is None or prev in ' \t\n\r([{'
                    out.append('\u201c' if opening else '\u201d')
                else:
                    out.append(ch)
            result = ''.join(out)
        if has_single:
            out, chars = [], list(result)
            for i, ch in enumerate(chars):
                if ch == "'":
                    prev = chars[i - 1] if i > 0 else None
                    nxt = chars[i + 1] if i < len(chars) - 1 else None
                    # apostrophe in contraction → right single quote
                    if prev and nxt and prev.isalpha() and nxt.isalpha():
                        out.append('\u2019')
                    else:
                        opening = prev is None or prev in ' \t\n\r([{'
                        out.append('\u2018' if opening else '\u2019')
                else:
                    out.append(ch)
            result = ''.join(out)
        return result

    @staticmethod
    def _strip_trailing_whitespace(s: str) -> str:
        return '\n'.join(line.rstrip() for line in s.split('\n'))

    async def write_file(self, path: str, content: str):
        """Write content to a file.

        Args:
            path(`path`): The relative file path to write into, a prefix dir will be automatically concatenated.
            content:

        Returns:
            <OK> or error message.
        """
        try:
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir, exist_ok=True)
            original_path = path  # Preserve original path for error messages
            real_path = self.get_real_path(path)
            if real_path is None:
                return f'<{original_path}> is out of the valid project path: {self.output_dir}'
            dirname = os.path.dirname(real_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            with open(real_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f'Save file <{path}> successfully.'
        except Exception as e:
            return f'Write file <{path}> failed, error: ' + str(e)

    def get_real_path(self, path):
        # Check if path is absolute or already starts with output_dir
        if os.path.isabs(path):
            target_path = path
        elif path.startswith(self.output_dir + os.sep) or path.startswith(
                self.output_dir):
            # Path already includes output_dir as prefix
            target_path = path
        else:
            target_path = os.path.join(self.output_dir, path)
        target_path_real = os.path.realpath(target_path)
        output_dir_real = os.path.realpath(self.output_dir)
        is_in_output_dir = target_path_real.startswith(
            output_dir_real + os.sep) or target_path_real == output_dir_real

        if not is_in_output_dir and not self.allow_read_all_files:
            logger.warning(
                f'Attempt to read file outside output directory blocked: {path} -> {target_path_real}'
            )
            return None
        else:
            return target_path_real

    async def read_file(self,
                        paths: list[str],
                        offset: int = None,
                        limit: int = None,
                        abbreviate: bool = False):
        """Read the content of file(s).

        Args:
            paths: List of relative file path(s) to read.
            offset: Line number to start reading from (1-based). Only effective for a single file.
            limit: Number of lines to read. Only effective for a single file.
            abbreviate: If True, return an LLM-generated summary instead of raw content.

        Returns:
            Dictionary mapping file path(s) to their content or error messages.
        """
        if abbreviate:
            return await self._read_files_abbreviated(paths)

        results = {}
        use_line_range = len(paths) == 1 and (offset is not None
                                              or limit is not None)

        for path in paths:
            try:
                target_path_real = self.get_real_path(path)
                if target_path_real is None:
                    results[path] = (
                        f'Access denied: Reading file <{path}> outside output directory is not allowed. '
                        f'Set allow_read_all_files=true in config to enable.')
                    continue

                ext = os.path.splitext(path)[1].lstrip('.').lower()

                # --- Image files ---
                if ext in self.IMAGE_EXTENSIONS:
                    with open(target_path_real, 'rb') as f:
                        raw = f.read()
                    media_type = f'image/{ext}' if ext != 'jpg' else 'image/jpeg'
                    results[path] = {
                        'type': 'image',
                        'media_type': media_type,
                        'base64': base64.b64encode(raw).decode('ascii'),
                    }
                    continue

                # --- Text files ---
                file_size = os.path.getsize(target_path_real)
                if file_size > self.MAX_READ_BYTES and not use_line_range:
                    results[path] = (
                        f'Error: File <{path}> is too large ({file_size} bytes). '
                        f'Use offset and limit to read specific portions.')
                    continue

                # Dedup: return stub if file unchanged since last read
                mtime = os.path.getmtime(target_path_real)
                cached = self._read_cache.get(target_path_real)
                if (cached
                        and cached['mtime'] == mtime
                        and cached['offset'] == offset
                        and cached['limit'] == limit):
                    results[path] = {
                        'type': 'file_unchanged',
                        'message': 'File has not changed since last read.',
                    }
                    continue

                with open(target_path_real, 'rb') as f:
                    raw_bytes = f.read()

                try:
                    content = raw_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    results[path] = (
                        f'Error: File <{path}> appears to be binary. '
                        f'Only text and image files are supported.')
                    continue

                # Normalize line endings
                content = content.replace('\r\n', '\n')
                lines = content.splitlines(keepends=True)
                total_lines = len(lines)

                if use_line_range:
                    actual_start = max(1, offset) if offset is not None else 1
                    actual_end = min(actual_start + limit - 1, total_lines) if limit is not None else total_lines

                    if actual_start > total_lines:
                        results[path] = f'Error: offset {offset} exceeds file length ({total_lines} lines)'
                        continue
                    selected = lines[actual_start - 1:actual_end]
                    start_lineno = actual_start
                else:
                    selected = lines
                    start_lineno = 1

                results[path] = ''.join(
                    f'{start_lineno + i}\t{line}'
                    for i, line in enumerate(selected)
                )

                # Update dedup cache
                self._read_cache[target_path_real] = {
                    'mtime': mtime,
                    'offset': offset,
                    'limit': limit,
                }

            except FileNotFoundError:
                results[path] = f'Read file <{path}> failed: FileNotFound'
            except Exception as e:
                results[path] = f'Read file <{path}> failed, error: ' + str(e)
        return json.dumps(results, indent=2, ensure_ascii=False)

    async def _read_files_abbreviated(self, paths: list[str]) -> str:
        results = {}

        def process_file(path):
            try:
                target_path_real = self.get_real_path(path)
                if target_path_real is None:
                    return path, f'Access denied: Reading file <{path}> outside output directory is not allowed.'

                index_file = os.path.join(self.index_dir, path.strip(os.sep))
                if os.path.exists(index_file):
                    src_mtime = os.path.getmtime(target_path_real)
                    idx_mtime = os.path.getmtime(index_file)
                    if idx_mtime >= src_mtime:
                        with open(index_file, 'r', encoding='utf-8') as f:
                            return path, f.read()

                with open(target_path_real, 'r', encoding='utf-8') as f:
                    content = f.read()

                messages = [
                    Message(role='system', content=self.system),
                    Message(role='user', content='The content to be abbreviated:\n\n' + content),
                ]
                response = self.llm.generate(messages=messages, stream=False)
                os.makedirs(os.path.dirname(index_file), exist_ok=True)
                with open(index_file, 'w', encoding='utf-8') as f:
                    f.write(response.content)
                return path, response.content
            except FileNotFoundError:
                return path, f'Read file <{path}> failed: FileNotFound'
            except Exception as e:
                return path, f'Process file <{path}> failed, error: ' + str(e)

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_path = {executor.submit(process_file, p): p for p in paths}
            for future in as_completed(future_to_path):
                path, result = future.result()
                results[path] = result

        return json.dumps(results, indent=2, ensure_ascii=False)

    async def edit_file(self,
                        path: str = None,
                        old_string: str = None,
                        new_string: str = None,
                        replace_all: bool = False):
        """Edit a file by replacing an exact string with new content.

        Args:
            path: The relative file path to edit.
            old_string: The exact string to find and replace.
            new_string: The replacement string.
            replace_all: If True, replace all occurrences. Default replaces only the first.

        Returns:
            Success or error message.
        """
        try:
            if old_string is None:
                return 'Error: `old_string` is required.'
            if new_string is None:
                return 'Error: `new_string` is required.'

            target_path_real = self.get_real_path(path)
            if target_path_real is None:
                return f'<{path}> is out of the valid project path: {self.output_dir}'

            # --- Special case: old_string="" ---
            if old_string == '':
                if not os.path.exists(target_path_real):
                    # Create new file
                    os.makedirs(os.path.dirname(target_path_real), exist_ok=True)
                    with open(target_path_real, 'w', encoding='utf-8') as f:
                        f.write(new_string)
                    return f'Created file <{path}> successfully.'
                with open(target_path_real, 'rb') as f:
                    existing = f.read()
                try:
                    existing_text = existing.decode('utf-8')
                except UnicodeDecodeError:
                    return f'Error: File <{path}> appears to be binary and cannot be edited as text.'
                if existing_text.strip() != '':
                    return (
                        'Error: `old_string` is empty but the file already has content. '
                        'Use `write_file` for a full rewrite, or provide an `old_string` anchor to insert content.'
                    )
                with open(target_path_real, 'w', encoding='utf-8') as f:
                    f.write(new_string)
                return f'Edit file <{path}> successfully (filled empty file).'

            if not os.path.exists(target_path_real):
                return f'Error: File <{path}> does not exist.'

            with open(target_path_real, 'rb') as f:
                raw = f.read()
            try:
                content = raw.decode('utf-8')
            except UnicodeDecodeError:
                return f'Error: File <{path}> appears to be binary and cannot be edited as text.'

            # Normalize line endings for matching
            content = content.replace('\r\n', '\n')
            old_string = old_string.replace('\r\n', '\n')

            # --- Fallback 1: exact match ---
            actual_old = old_string if old_string in content else None

            # --- Fallback 2: quote normalization ---
            if actual_old is None:
                norm_old = self._normalize_quotes(old_string)
                norm_content = self._normalize_quotes(content)
                idx = norm_content.find(norm_old)
                if idx != -1:
                    actual_old = content[idx:idx + len(old_string)]

            if actual_old is None:
                return (
                    f'Error: `old_string` not found in <{path}>. '
                    f'Make sure it matches the file content exactly including whitespace.'
                )

            count = content.count(actual_old)
            if count > 1 and not replace_all:
                return (
                    f'Error: Found {count} occurrences of `old_string` in <{path}>. '
                    f'Add more surrounding context to make it unique, or set replace_all=true.'
                )

            # Apply quote style preservation to new_string
            actual_new = self._preserve_quote_style(old_string, actual_old, new_string)

            # --- Fallback 3: smart delete — strip trailing newline when deleting ---
            if actual_new == '' and not actual_old.endswith('\n') and actual_old + '\n' in content:
                actual_old = actual_old + '\n'

            # Strip trailing whitespace from new_string (skip markdown files)
            is_markdown = path.lower().endswith(('.md', '.mdx'))
            if not is_markdown:
                actual_new = self._strip_trailing_whitespace(actual_new)

            if replace_all:
                updated = content.replace(actual_old, actual_new)
            else:
                updated = content.replace(actual_old, actual_new, 1)

            with open(target_path_real, 'w', encoding='utf-8') as f:
                f.write(updated)

            replaced = count if replace_all else 1
            return f'Edit file <{path}> successfully ({replaced} occurrence(s) replaced).'
        except Exception as e:
            return f'Edit file <{path}> failed, error: ' + str(e)


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
