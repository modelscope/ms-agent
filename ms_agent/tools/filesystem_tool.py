# Copyright (c) Alibaba, Inc. and its affiliates.
import fnmatch
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import json
from ms_agent.config import Config
from ms_agent.llm import LLM
from ms_agent.llm.utils import Message, Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_INDEX_DIR, DEFAULT_OUTPUT_DIR

logger = get_logger()


class FileSystemTool(ToolBase):
    """A file system operation tool"""

    # Directories to exclude from file operations
    EXCLUDED_DIRS = {
        'node_modules', 'dist', '.git', '__pycache__', '.venv', 'venv'
    }
    # File prefixes to exclude
    EXCLUDED_FILE_PREFIXES = ('.', '..', '__pycache__')

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
        system = Config.safe_get_config(
            self.config, 'tools.file_system.system_for_abbreviations')
        if system:
            self.system = system

    async def connect(self):
        logger.warning_once(
            '[IMPORTANT]FileSystemTool is not implemented with sandbox, please consider other similar '
            'tools if you want to run dangerous code.')

    async def _get_tools_inner(self):
        tools = {
            'file_system': [
                Tool(
                    tool_name='create_directory',
                    server_name='file_system',
                    description='Create a directory',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type':
                                'string',
                                'description':
                                'The relative path of the directory to create',
                            }
                        },
                        'required': ['path'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='write_file',
                    server_name='file_system',
                    description='Write content into a file',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type': 'string',
                                'description': 'The relative path of the file',
                            },
                            'content': {
                                'type': 'string',
                                'description': 'The content of the file',
                            },
                        },
                        'required': ['path', 'content'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='read_abbreviation_file',
                    server_name='file_system',
                    description=
                    'Read the abbreviation content of file(s). If the information is not enough, '
                    'read the original file by `read_file`',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'paths': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                'List of relative file path(s) to read, format: {"paths": ["file1", "file2"]}"]}',
                            },
                        },
                        'required': ['paths'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='read_file',
                    server_name='file_system',
                    description=
                    'Read the content of file(s). When reading a single file, optionally specify line range.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'paths': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                'List of relative file path(s) to read, format: {"paths": ["file1", "file2"]}"]}',
                            },
                            'start_line': {
                                'type':
                                'integer',
                                'description':
                                'Start line number (1-based, inclusive). Only effective when paths has exactly one '
                                'element. 0 or omit to read from beginning.',
                            },
                            'end_line': {
                                'type':
                                'integer',
                                'description':
                                'End line number (1-based, inclusive). Only effective when paths has exactly one '
                                'element. Omit to read to the end.',
                            },
                        },
                        'required': ['paths'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='list_files',
                    server_name='file_system',
                    description='List all files in a directory',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type':
                                'string',
                                'description':
                                "The path to list files, if path is None or '' or not given, "
                                'the root dir will be used as path.',
                            }
                        },
                        'required': [],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='delete_file_or_dir',
                    server_name='file_system',
                    description='Delete one file or one directory',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type': 'string',
                                'description': 'The relative path to delete',
                            }
                        },
                        'required': ['path'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='search_file_content',
                    server_name='file_system',
                    description=
                    'Search for content in files using literal text or regex patterns. '
                    'Automatically detects and supports both literal string matching and regex pattern matching. '
                    'Returns matching files with line numbers and surrounding context.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'content': {
                                'type':
                                'string',
                                'description':
                                'The content/text or regex pattern to search for. '
                                'Supports both literal strings and regex patterns automatically.',
                            },
                            'parent_path': {
                                'type':
                                'string',
                                'description':
                                'The relative parent path to search in (optional, defaults to root)',
                            },
                            'file_pattern': {
                                'type':
                                'string',
                                'description':
                                'Wildcard pattern for file names, e.g., "*.py", "*.js", "test_*.py" '
                                '(default: "*" for all files)',
                            },
                            'context_lines': {
                                'type':
                                'integer',
                                'description':
                                'Number of lines before and after the match to include (default: 2)',
                            },
                        },
                        'required': ['content'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='search_file_name',
                    server_name='file_system',
                    description=
                    'Search for files by name using regex pattern matching. '
                    'Supports both regex patterns and simple substring matching. '
                    'If the file parameter is a valid regex pattern, it will be used for regex matching; '
                    'otherwise, falls back to substring matching. '
                    'The parent_path can also be a regex pattern to filter directories.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'file': {
                                'type':
                                'string',
                                'description':
                                'The filename pattern to search for (supports regex, e.g., r"\\.js$" for .js files, '
                                'or "service" for substring match).',
                            },
                            'parent_path': {
                                'type':
                                'string',
                                'description':
                                'The relative parent path to search in (supports regex for directory filtering, '
                                'e.g., r"backend.*" to match backend-related directories). '
                                'Defaults to root if not specified.',
                            },
                        },
                        'required': ['file'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='replace_file_lines',
                    server_name='file_system',
                    description=
                    'Replace specific line ranges in a file. Supports inserting at beginning '
                    '(start_line=0) or end (start_line=-1). '
                    'Line numbers are 1-based and inclusive on both ends.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type':
                                'string',
                                'description':
                                'The relative path of the file to modify',
                            },
                            'content': {
                                'type': 'string',
                                'description':
                                'The new content to insert/replace',
                            },
                            'start_line': {
                                'type':
                                'integer',
                                'description':
                                'Start line number (1-based, inclusive). Use 0 to insert at beginning, '
                                '-1 to append at end',
                            },
                            'end_line': {
                                'type':
                                'integer',
                                'description':
                                'End line number (1-based, inclusive). Required unless start_line is 0 or -1',
                            },
                        },
                        'required': ['path', 'content', 'start_line'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='replace_file_contents',
                    server_name='file_system',
                    description=
                    'Replace exact content in a file without using line numbers. '
                    'You must provide:'
                    '[Required]path: The relative path of modified file.\n'
                    '[Required]source: The old content to be replaced\n'
                    '[Required]target: The new content to replace the `source`\n'
                    'Do not miss any of these arguments!',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type':
                                'string',
                                'description':
                                'The relative path of the file to modify',
                            },
                            'source': {
                                'type':
                                'string',
                                'description':
                                'The exact content to find and replace (must match exactly including whitespace)',
                            },
                            'target': {
                                'type': 'string',
                                'description':
                                'The new content to replace with',
                            },
                            'occurrence': {
                                'type':
                                'integer',
                                'description':
                                'Which occurrence to replace (1-based). Use -1 to replace all occurrences. '
                                'Default is -1 (all occurrences).',
                            },
                        },
                        'required': ['path', 'source', 'target'],
                        'additionalProperties': False
                    }),
            ]
        }
        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await getattr(self, tool_name)(**tool_args)

    async def create_directory(self, path: Optional[str] = None) -> str:
        """Create a directory

        Args:
            path(`str`): The relative directory path to create, a prefix dir will be automatically concatenated.

        Returns:
            <OK> or error message.
        """
        try:
            if not path:
                path = self.output_dir
            else:
                path = os.path.join(self.output_dir, path)
            os.makedirs(path, exist_ok=True)
            return f'Directory: <{path or "root path"}> was created.'
        except Exception as e:
            return f'Create directory <{path or "root path"}> failed, error: ' + str(
                e)

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
            path = self.get_real_path(path)
            if path is None:
                return f'<{path}> is out of the valid project path: {self.output_dir}'
            dirname = os.path.dirname(path)
            if dirname:
                os.makedirs(
                    os.path.join(self.output_dir, dirname), exist_ok=True)
            with open(os.path.join(self.output_dir, path), 'w') as f:
                f.write(content)
            return f'Save file <{path}> successfully.'
        except Exception as e:
            return f'Write file <{path}> failed, error: ' + str(e)

    async def replace_file_contents(self,
                                    path: str,
                                    source: str = None,
                                    target: str = None,
                                    occurrence: int = -1):
        """Replace exact content in a file without using line numbers.

        This method is safer for parallel operations as it doesn't rely on line numbers
        that might change when multiple agents modify the same file concurrently.

        Args:
            path(str): The relative file path to modify
            source(str): The exact content to find and replace (must match exactly including whitespace)
            target(str): The new content to replace with
            occurrence(int): Which occurrence to replace (1-based). Use -1 to replace all occurrences.
                           Default is -1 (all occurrences).

        Returns:
            Success or error message.
        """
        try:
            if not source:
                return 'Error: You MUST provide the `source` parameter to be replaced with the `target`.'
            if not target:
                return 'Error: You MUST provide the `target` parameter to replace the `source`'
            target_path_real = self.get_real_path(path)
            if target_path_real is None:
                return f'<{path}> is out of the valid project path: {self.output_dir}'

            # Read file content
            if not os.path.exists(target_path_real):
                return f'Error: File <{path}> does not exist'

            with open(target_path_real, 'r', encoding='utf-8') as f:
                file_content = f.read()

            # Check if source exists
            if source not in file_content:
                return (
                    f'Error: Could not find the exact content to replace in <{path}>. '
                    f'Make sure the content matches exactly including all whitespace.'
                )

            # Count occurrences
            count = file_content.count(source)

            # Replace based on occurrence parameter
            if occurrence == -1:
                # Replace all occurrences
                updated_content = file_content.replace(source, target)
                operation_msg = f'Replaced all {count} occurrence(s)'
            elif occurrence < 1:
                return f'Error: occurrence must be >= 1 or -1 (for all), got {occurrence}'
            elif occurrence > count:
                return f'Error: occurrence {occurrence} exceeds total occurrences ({count}) of the content'
            else:
                # Replace specific occurrence
                parts = file_content.split(source, occurrence)
                if len(parts) <= occurrence:
                    return f'Error: Could not find occurrence {occurrence} of the content'
                # Rejoin: first (occurrence-1) parts with source, then target, then the rest
                updated_content = source.join(
                    parts[:occurrence]) + target + source.join(
                        parts[occurrence:])
                operation_msg = f'Replaced occurrence {occurrence} of {count}'

            # Write back to file
            with open(target_path_real, 'w', encoding='utf-8') as f:
                f.write(updated_content)

            return f'{operation_msg} in file <{path}> successfully.'

        except Exception as e:
            return f'Replace content in file <{path}> failed, error: ' + str(e)

    async def replace_file_lines(self,
                                 path: str,
                                 content: str,
                                 start_line: int,
                                 end_line: int = None):
        """Replace specific line ranges in a file.

        Args:
            path(str): The relative file path to modify, a prefix dir will be automatically concatenated.
            content(str): The new content to insert/replace
            start_line(int): Start line number (1-based, inclusive). Use 0 to insert at beginning, -1 to append at end
            end_line(int): End line number (1-based, inclusive). Optional for start_line=0 or -1

        Returns:
            Success or error message.
        """
        try:
            target_path_real = self.get_real_path(path)
            if target_path_real is None:
                return f'<{path}> is out of the valid project path: {self.output_dir}'
            file_path = target_path_real
            # Read existing file content
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            else:
                # If file doesn't exist, create it
                dirname = os.path.dirname(file_path)
                if dirname:
                    os.makedirs(dirname, exist_ok=True)
                lines = []

            total_lines = len(lines)

            # Ensure content ends with newline if it doesn't already
            if content and not content.endswith('\n'):
                content += '\n'

            # Handle special cases
            if start_line == 0:
                # Insert at beginning
                new_lines = [content] + lines
                operation = 'Inserted at beginning'
            elif start_line == -1:
                # Append at end
                new_lines = lines + [content]
                operation = 'Appended at end'
            else:
                # Replace range (1-based, inclusive)
                if end_line is None:
                    return 'Error: end_line is required when start_line is not 0 or -1'

                if start_line < 1 or start_line > total_lines + 1:
                    return f'Error: start_line {start_line} is out of range (file has {total_lines} lines)'

                if end_line < start_line:
                    return f'Error: end_line {end_line} must be >= start_line {start_line}'

                # Convert to 0-based indices
                start_idx = start_line - 1
                # end_line is inclusive (1-based), so we keep lines from end_line onwards (0-based)
                end_idx = end_line
                # Lines to keep start from index end_line (which is the line after end_line in 1-based)

                new_lines = lines[:start_idx] + [content] + lines[end_idx:]
                operation = f'Replaced lines {start_line}-{end_line}'

            # Write back to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            target = '\n'.join(new_lines).split('\n')
            return f'{operation} in file <{path}> successfully. New file has {len(target)} lines.'

        except Exception as e:
            return f'Replace lines in file <{path}> failed, error: ' + str(e)

    def get_real_path(self, path):
        if os.path.isabs(path) or os.path.basename(self.output_dir) in path:
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

    async def read_abbreviation_file(self, paths: list[str]):
        results = {}

        def process_file(path):
            try:
                target_path_real = self.get_real_path(path)
                if target_path_real is None:
                    return path, f'Access denied: Reading file <{path}> outside output directory is not allowed.'

                index_file = os.path.join(self.index_dir, path.strip(os.sep))
                if os.path.exists(index_file):
                    with open(index_file, 'r', encoding='utf-8') as f:
                        return path, f.read()

                # Read file content
                with open(target_path_real, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Use LLM to generate abbreviation
                messages = [
                    Message(role='system', content=self.system),
                    Message(
                        role='user',
                        content='The content to be abbreviated:\n\n'
                        + content),
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

        # Use thread pool for parallel LLM API calls
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_path = {
                executor.submit(process_file, p): p
                for p in paths
            }
            for future in as_completed(future_to_path):
                path, result = future.result()
                results[path] = result

        return json.dumps(results, indent=2, ensure_ascii=False)

    async def read_file(self,
                        paths: list[str],
                        start_line: int = 0,
                        end_line: int = None):
        """Read the content of file(s).

        Args:
            paths(`list[str]`): List of relative file path(s) to read, a prefix dir will be automatically concatenated.
            start_line(int): Start line number (1-based, inclusive). Only effective when paths has exactly one element.
                0 means from the beginning.
            end_line(int): End line number (1-based, inclusive). Only effective when paths has exactly one element.
                None means to the end.

        Returns:
            Dictionary mapping file path(s) to their content or error messages.
        """
        results = {}
        # Line range is only effective when reading a single file
        use_line_range = len(paths) == 1 and (start_line > 0
                                              or end_line is not None)

        for path in paths:
            try:
                target_path_real = self.get_real_path(path)
                if target_path_real is None:
                    results[path] = (
                        f'Access denied: Reading file <{path}> outside output directory is not allowed. '
                        f'Set allow_read_all_files=true in config to enable.')
                    continue

                with open(target_path_real, 'r') as f:
                    if use_line_range:
                        # Read specific line range
                        lines = f.readlines()
                        total_lines = len(lines)

                        # Validate and adjust line numbers (1-based)
                        actual_start = max(1,
                                           start_line) if start_line > 0 else 1
                        actual_end = min(
                            end_line, total_lines
                        ) if end_line is not None else total_lines

                        if actual_start > total_lines:
                            results[
                                path] = f'Error: start_line {start_line} exceeds file length ({total_lines} lines)'
                        elif actual_start > actual_end:
                            results[
                                path] = f'Error: start_line {actual_start} > end_line {actual_end}'
                        else:
                            # Convert to 0-based index, end_line is inclusive
                            selected_lines = lines[actual_start - 1:actual_end]
                            results[path] = ''.join(selected_lines)
                    else:
                        # Read entire file
                        results[path] = f.read()
            except FileNotFoundError:
                results[path] = f'Read file <{path}> failed: FileNotFound'
            except Exception as e:
                results[path] = f'Read file <{path}> failed, error: ' + str(e)
        return json.dumps(results, indent=2, ensure_ascii=False)

    async def delete_file_or_dir(self, path: str):
        """Delete a file or a directory.

        Args:
            path(str): The file or directory to delete, a prefix dir will be automatically concatenated.

        Returns:
            boolean
        """
        abs_path = os.path.join(self.output_dir, path)
        if os.path.exists(abs_path):
            try:
                if os.path.isfile(abs_path):
                    os.remove(abs_path)
                else:
                    shutil.rmtree(abs_path)
                return f'Path deleted: <{path}>'
            except Exception as e:
                return f'Delete file <{path}> failed, error: ' + str(e)
        else:
            return f'Path not found: {path}'

    async def search_file_name(self, file: str = '', parent_path: str = ''):
        """Search for files by name using regex pattern matching.

        Args:
            file(str): File name pattern (supports regex). If it's a valid regex pattern,
                      it will be used for regex matching; otherwise, falls back to substring matching.
            parent_path(str): Parent path pattern (supports regex for filtering directories).
                             Can be a simple path or a regex pattern to match directory paths.

        Returns:
            String containing all matched file paths
        """
        parent_path = parent_path or ''
        target_path_real = self.get_real_path(parent_path)
        if target_path_real is None:
            return f'<{parent_path}> is out of the valid project path: {self.output_dir}'
        _parent_path = target_path_real
        assert os.path.isdir(
            _parent_path
        ), f'Parent path <{parent_path}> does not exist, it should be a inner relative path of the project folder.'

        # Try to compile file pattern as regex
        file_use_regex = False
        file_pattern = None
        if file:
            try:
                file_pattern = re.compile(file)
                file_use_regex = True
            except re.error:
                file_use_regex = False

        # Try to compile parent_path filter as regex (optional)
        path_use_regex = False
        path_pattern = None
        if parent_path:
            try:
                path_pattern = re.compile(parent_path)
                path_use_regex = True
            except re.error:
                path_use_regex = False

        all_found_files = []
        for root, dirs, files in os.walk(_parent_path):
            if path_use_regex and parent_path:
                relative_root = os.path.relpath(root, self.output_dir)
                if not path_pattern.search(relative_root):
                    continue

            for filename in files:
                if file:
                    if file_use_regex:
                        is_match = file_pattern.search(filename) is not None
                    else:
                        is_match = file in filename
                else:
                    is_match = True  # No filter, match all files

                if is_match:
                    file_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(file_path, self.output_dir)
                    all_found_files.append(relative_path)

        if not all_found_files:
            return f'No files found matching pattern <{file or "*"}> in <{parent_path or "root"}>'

        all_found_files = '\n'.join(all_found_files)
        return f'Found {len(all_found_files.splitlines())} file(s) matching <{file or "*"}>:\n{all_found_files}'

    async def search_file_content(self,
                                  content: str = None,
                                  parent_path: str = None,
                                  file_pattern: str = '*',
                                  context_lines: int = 2):
        """Search for content in files using thread pool.
        Supports both literal string matching and regex pattern matching automatically.

        Args:
            content(str): The content or regex pattern to search for (auto-detected)
            parent_path(str): The relative parent path to search in
            file_pattern(str): Wildcard pattern for file names (default: '*' for all files)
            context_lines(int): Number of lines before and after the match to include (default: 2)

        Returns:
            String containing all matches with file path, line number, and context
        """
        if parent_path.startswith('.' + os.sep):
            parent_path = parent_path[len('.' + os.sep):]
        if parent_path == '.':
            parent_path = ''
        target_path_real = self.get_real_path(parent_path)
        if target_path_real is None:
            return f'<{parent_path}> is out of the valid project path: {self.output_dir}'
        _parent_path = target_path_real
        assert os.path.isdir(
            _parent_path
        ), f'Parent path <{parent_path}> does not exist, it should be a inner relative path of the project folder.'

        if not content:
            return 'Error: content parameter is required for search'

        # Try to compile as regex pattern, fallback to literal string matching
        use_regex = False
        pattern = None
        try:
            pattern = re.compile(content)
            use_regex = True
        except re.error:
            # Not a valid regex, will use literal string matching
            use_regex = False

        # Collect all files matching the pattern
        files_to_search = []
        for root, dirs, files in os.walk(_parent_path):
            try:
                test_dir = str(Path(root).relative_to(self.output_dir))
            except ValueError:
                test_dir = str(root)
            if test_dir == '.':
                test_dir = ''
            if any(excluded_dir in root
                   for excluded_dir in self.EXCLUDED_DIRS):
                continue
            for filename in files:
                # Skip excluded files
                if filename.startswith(
                        self.EXCLUDED_FILE_PREFIXES) or test_dir.startswith(
                            self.EXCLUDED_FILE_PREFIXES):
                    continue
                # Match file pattern
                if fnmatch.fnmatch(filename, file_pattern):
                    files_to_search.append(os.path.join(root, filename))

        if not files_to_search:
            return f'No files matching pattern <{file_pattern}> found in <{parent_path or "root"}>'

        # Function to search in a single file
        def search_in_file(file_path):
            matches = []
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line_num, line in enumerate(lines, start=1):
                    # Check for match: regex or literal string
                    is_match = False
                    if use_regex:
                        is_match = pattern.search(line) is not None
                    else:
                        is_match = content in line

                    if is_match:
                        # Calculate context range
                        start_line = max(0, line_num - context_lines - 1)
                        end_line = min(len(lines), line_num + context_lines)

                        # Extract context lines
                        context = []
                        for i in range(start_line, end_line):
                            prefix = '> ' if i == line_num - 1 else '  '
                            context.append(
                                f'{prefix}{i + 1:4d} | {lines[i].rstrip()}')

                        relative_path = os.path.relpath(
                            file_path, self.output_dir)
                        matches.append({
                            'file': relative_path,
                            'line': line_num,
                            'context': '\n'.join(context)
                        })
            return matches

        # Use thread pool to search files in parallel
        all_matches = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_file = {
                executor.submit(search_in_file, f): f
                for f in files_to_search
            }
            for future in as_completed(future_to_file):
                matches = future.result()
                all_matches.extend(matches)

        if not all_matches:
            return f'No matches found for <{content}> in files matching <{file_pattern}>'

        # Format results
        result_lines = [
            f'Found {len(all_matches)} match(es) for "{content}":\n'
        ]
        for match in all_matches:
            result_lines.append(
                f"File: {match['file']}, Line: {match['line']}")
            result_lines.append(match['context'])
            result_lines.append('')

        return '\n'.join(result_lines)

    async def list_files(self, path: str = None):
        """List all files in a directory.

        Args:
            path: The relative path to traverse, a prefix dir will be automatically concatenated.

        Returns:
            The file names concatenated as a string
        """
        file_paths = []
        if not path or path == '.':
            path = self.output_dir
        else:
            path = os.path.join(self.output_dir, path)
        if path.startswith('.' + os.sep):
            path = path[len('.' + os.sep):]
        try:
            for root, dirs, files in os.walk(path):
                try:
                    test_dir = str(Path(root).relative_to(self.output_dir))
                except ValueError:
                    test_dir = str(root)
                if test_dir == '.':
                    test_dir = ''
                for file in files:
                    # Skip excluded directories and files
                    root_exclude = any(excluded_dir in root
                                       for excluded_dir in self.EXCLUDED_DIRS)
                    if root_exclude or file.startswith(
                            self.EXCLUDED_FILE_PREFIXES
                    ) or test_dir.startswith(self.EXCLUDED_FILE_PREFIXES):
                        continue
                    absolute_path = os.path.join(root, file)
                    relative_path = os.path.relpath(absolute_path, path)
                    file_paths.append(relative_path)
            return '\n'.join(file_paths) or f'No files in path: {path}'
        except Exception as e:
            return f'List files of <{path or "root path"}> failed, error: ' + str(
                e)
