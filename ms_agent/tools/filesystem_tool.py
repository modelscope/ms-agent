# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from typing import Optional

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR

logger = get_logger()


class FileSystemTool(ToolBase):
    """A file system operation tool

    TODO: This tool now is a simple implementation, sandbox or mcp TBD.
    """

    def __init__(self, config):
        super(FileSystemTool, self).__init__(config)
        self.exclude_func(getattr(config.tools, 'file_system', None))
        self.output_dir = getattr(config, 'output_dir', DEFAULT_OUTPUT_DIR)

    async def connect(self):
        logger.warning_once(
            '[IMPORTANT]FileSystemTool is not implemented with sandbox, please consider other similar '
            'tools if you want to run dangerous code.')

    async def get_tools(self):
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
                    description='Read the content of file(s)',
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
                            }
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
            ]
        }
        return {
            'file_system': [
                t for t in tools['file_system']
                if t['tool_name'] not in self.exclude_functions
            ]
        }

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
            dirname = os.path.dirname(path)
            if dirname:
                os.makedirs(
                    os.path.join(self.output_dir, dirname), exist_ok=True)
            with open(os.path.join(self.output_dir, path), 'w') as f:
                f.write(content)
            return f'Save file <{path}> successfully.'
        except Exception as e:
            return f'Write file <{path}> failed, error: ' + str(e)

    async def read_file(self, paths: list[str]):
        """Read the content of file(s).

        Args:
            paths(`list[str]`): List of relative file path(s) to read, a prefix dir will be automatically concatenated.

        Returns:
            Dictionary mapping file path(s) to their content or error messages.
        """
        results = {}
        for path in paths:
            try:
                with open(os.path.join(self.output_dir, path), 'r') as f:
                    results[path] = f.read()
            except Exception as e:
                results[path] = f'Read file <{path}> failed, error: ' + str(e)
        return str(results)

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
                    if 'node_modules' in root or 'dist' in root or file.startswith(
                            '.'):
                        continue
                    absolute_path = os.path.join(root, file)
                    relative_path = os.path.relpath(absolute_path, path)
                    file_paths.append(relative_path)
            return '\n'.join(file_paths)
        except Exception as e:
            return f'List files of <{path or "root path"}> failed, error: ' + str(
                e)
