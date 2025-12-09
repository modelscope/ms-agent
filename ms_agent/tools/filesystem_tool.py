# Copyright (c) Alibaba, Inc. and its affiliates.
import fnmatch
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR

logger = get_logger()


class FileSystemTool(ToolBase):
    """A file system operation tool

    TODO: This tool now is a simple implementation, sandbox or mcp TBD.
    """

    # Directories to exclude from file operations
    EXCLUDED_DIRS = {
        'node_modules', 'dist', '.git', '__pycache__', '.venv', 'venv'
    }
    # File prefixes to exclude
    EXCLUDED_FILE_PREFIXES = ('.', '..')

    def __init__(self, config, **kwargs):
        super(FileSystemTool, self).__init__(config)
        self.exclude_func(getattr(config.tools, 'file_system', None))
        self.output_dir = getattr(config, 'output_dir', DEFAULT_OUTPUT_DIR)
        self.trust_remote_code = kwargs.get('trust_remote_code', False)
        self.allow_read_all_files = getattr(
            getattr(config.tools, 'file_system', {}), 'allow_read_all_files',
            False)
        if not self.trust_remote_code:
            self.allow_read_all_files = False

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
                                'List of relative file path(s) to read',
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
                    'Search for content in files using wildcard patterns. '
                    'Returns matching files with line numbers and surrounding context.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'content': {
                                'type':
                                'string',
                                'description':
                                'The content/text to search for in files',
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
                    'Search for files by name. Returns all file paths that contain the search '
                    'string in their filename.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'file': {
                                'type':
                                'string',
                                'description':
                                'The filename or partial filename to search for',
                            },
                            'parent_path': {
                                'type':
                                'string',
                                'description':
                                'The relative parent path to search in (optional, defaults to root)',
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
                end_idx = min(end_line, total_lines)  # end_line is inclusive

                new_lines = lines[:start_idx] + [content] + lines[end_idx:]
                operation = f'Replaced lines {start_line}-{end_line}'

            # Write back to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            new_content = '\n'.join(new_lines).split('\n')
            return f'{operation} in file <{path}> successfully. New file has {len(new_content)} lines.'

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

    async def read_file(self,
                        paths: list[str],
                        start_line: int = 0,
                        end_line: int = None):
        """Read the content of file(s).

        Args:
            paths(`list[str]`): List of relative file path(s) to read, a prefix dir will be automatically concatenated.
            start_line(int): Start line number (1-based, inclusive). Only effective when paths has exactly one element.
                0 means from beginning.
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

    async def search_file_name(self,
                               file: str = None,
                               parent_path: str = None):
        parent_path = parent_path or ''
        target_path_real = self.get_real_path(parent_path)
        if target_path_real is None:
            return f'<{parent_path}> is out of the valid project path: {self.output_dir}'
        _parent_path = target_path_real
        assert os.path.isdir(
            _parent_path
        ), f'Parent path <{parent_path}> does not exist, it should be a inner relative path of the project folder.'
        all_found_files = []
        for root, dirs, files in os.walk(_parent_path):
            for filename in files:
                if file in filename:
                    all_found_files.append(os.path.join(root, filename))
        all_found_files = '\n'.join(all_found_files)
        return f'The filenames containing the file name<{file}>: {all_found_files}'

    async def search_file_content(self,
                                  content: str = None,
                                  parent_path: str = None,
                                  file_pattern: str = '*',
                                  context_lines: int = 2):
        """Search for content in files using thread pool.

        Args:
            content(str): The content to search for
            parent_path(str): The relative parent path to search in
            file_pattern(str): Wildcard pattern for file names (default: '*' for all files)
            context_lines(int): Number of lines before and after the match to include (default: 2)

        Returns:
            String containing all matches with file path, line number, and context
        """
        target_path_real = self.get_real_path(parent_path)
        if target_path_real is None:
            return f'<{parent_path}> is out of the valid project path: {self.output_dir}'
        _parent_path = target_path_real
        assert os.path.isdir(
            _parent_path
        ), f'Parent path <{parent_path}> does not exist, it should be a inner relative path of the project folder.'

        if not content:
            return 'Error: content parameter is required for search'

        # Collect all files matching the pattern
        files_to_search = []
        for root, dirs, files in os.walk(_parent_path):
            # Skip excluded directories
            if any(excluded_dir in root
                   for excluded_dir in self.EXCLUDED_DIRS):
                continue
            for filename in files:
                # Skip excluded files
                if filename.startswith(self.EXCLUDED_FILE_PREFIXES):
                    continue
                # Match file pattern
                if fnmatch.fnmatch(filename, file_pattern):
                    files_to_search.append(os.path.join(root, filename))

        if not files_to_search:
            return f'No files matching pattern <{file_pattern}> found in <{parent_path or "root"}>'

        # Function to search in a single file
        def search_in_file(file_path):
            matches = []
            try:
                with open(
                        file_path, 'r', encoding='utf-8',
                        errors='ignore') as f:
                    lines = f.readlines()
                    for line_num, line in enumerate(lines, start=1):
                        if content in line:
                            # Calculate context range
                            start_line = max(0, line_num - context_lines - 1)
                            end_line = min(
                                len(lines), line_num + context_lines)

                            # Extract context lines
                            context = []
                            for i in range(start_line, end_line):
                                prefix = '> ' if i == line_num - 1 else '  '
                                context.append(
                                    f'{prefix}{i + 1:4d} | {lines[i].rstrip()}'
                                )

                            relative_path = os.path.relpath(
                                file_path, self.output_dir)
                            matches.append({
                                'file': relative_path,
                                'line': line_num,
                                'context': '\n'.join(context)
                            })
            except Exception as e:
                logger.debug(f'Error reading file {file_path}: {e}')
            return matches

        # Use thread pool to search files in parallel
        all_matches = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_file = {
                executor.submit(search_in_file, f): f
                for f in files_to_search
            }
            for future in as_completed(future_to_file):
                try:
                    matches = future.result()
                    all_matches.extend(matches)
                except Exception as e:
                    file_path = future_to_file[future]
                    logger.debug(f'Error processing {file_path}: {e}')

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
        if not path:
            path = self.output_dir
        else:
            path = os.path.join(self.output_dir, path)
        try:
            for root, dirs, files in os.walk(path):
                for file in files:
                    # Skip excluded directories and files
                    if any(excluded_dir in root
                           for excluded_dir in self.EXCLUDED_DIRS
                           ) or file.startswith(self.EXCLUDED_FILE_PREFIXES):
                        continue
                    absolute_path = os.path.join(root, file)
                    relative_path = os.path.relpath(absolute_path, path)
                    file_paths.append(relative_path)
            return '\n'.join(file_paths)
        except Exception as e:
            return f'List files of <{path or "root path"}> failed, error: ' + str(
                e)
