# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import shutil
from typing import Optional

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import MAX_CONTINUE_RUNS, get_logger, retry
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR
from openai import OpenAI

logger = get_logger()


class FileSystemTool(ToolBase):
    """A file system operation tool

    TODO: This tool now is a simple implementation, sandbox or mcp TBD.
    """

    def __init__(self, config, **kwargs):
        super(FileSystemTool, self).__init__(config)
        self.exclude_func(getattr(config.tools, 'file_system', None))
        self.output_dir = getattr(config, 'output_dir', DEFAULT_OUTPUT_DIR)
        if 'edit_file' not in self.exclude_functions:
            self.edit_file_config = getattr(config.tools.file_system,
                                            'edit_file_config', None)
            self.client = OpenAI(
                api_key=self.edit_file_config.api_key,
                base_url=self.edit_file_config.base_url)
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
                    tool_name='edit_file',
                    server_name='file_system',
                    description=
                    ('Use this tool to make an edit to an existing file.\n\n'
                     'This will be read by a less intelligent model, which will quickly apply the edit. '
                     'You should make it clear what the edit is, while also minimizing the unchanged code you write.\n'
                     'When writing the edit, you should specify each edit in sequence, with the special comment '
                     '// ... existing code ... to represent unchanged code in between edited lines.\n\n'
                     'For example:\n\n// ... existing code ...\nFIRST_EDIT\n// ... existing code ...\n'
                     'SECOND_EDIT\n// ... existing code ...\nTHIRD_EDIT\n// ... existing code ...\n\n'
                     'You should still bias towards repeating as few lines of the original file '
                     'as possible to convey the change.\n'
                     'But, each edit should contain minimally sufficient context of unchanged lines '
                     "around the code you're editing to resolve ambiguity.\n"
                     'DO NOT omit spans of pre-existing code (or comments) without using the '
                     '// ... existing code ... comment to indicate its absence. '
                     'If you omit the existing code comment, the model may inadvertently delete these lines.\n'
                     'If you plan on deleting a section, you must provide context before and after to delete it. '
                     'If the initial code is ```code \\n Block 1 \\n Block 2 \\n Block 3 \\n code```, '
                     'and you want to remove Block 2, you would output '
                     '```// ... existing code ... \\n Block 1 \\n  Block 3 \\n // ... existing code ...```.\n'
                     'Make sure it is clear what the edit should be, and where it should be applied.\n'
                     'Make edits to a file in a single edit_file call '
                     'instead of multiple edit_file calls to the same file. '
                     'The apply model can handle many distinct edits at once.'
                     ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type': 'string',
                                'description':
                                'Path of the target file to modify.'
                            },
                            'instructions': {
                                'type':
                                'string',
                                'description':
                                ('A single sentence instruction describing '
                                 'what you are going to do for the sketched edit. '
                                 'This is used to assist the less intelligent model in applying the edit. '
                                 'Use the first person to describe what you are going to do. '
                                 'Use it to disambiguate uncertainty in the edit.'
                                 )
                            },
                            'code_edit': {
                                'type':
                                'string',
                                'description':
                                ('Specify ONLY the precise lines of code that you wish to edit. '
                                 'NEVER specify or write out unchanged code. '
                                 'Instead, represent all unchanged code using the comment of the language '
                                 "you're editing in - example: // ... existing code ..."
                                 )
                            }
                        },
                        'required': ['path', 'instructions', 'code_edit']
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
                if os.path.isabs(path):
                    target_path = path
                else:
                    target_path = os.path.join(self.output_dir, path)
                target_path_real = os.path.realpath(target_path)
                output_dir_real = os.path.realpath(self.output_dir)
                is_in_output_dir = target_path_real.startswith(
                    output_dir_real
                    + os.sep) or target_path_real == output_dir_real

                if not is_in_output_dir and not self.allow_read_all_files:
                    results[path] = (
                        f'Access denied: Reading file <{path}> outside output directory is not allowed. '
                        f'Set allow_read_all_files=true in config to enable.')
                    logger.warning(
                        f'Attempt to read file outside output directory blocked: {path} -> {target_path_real}'
                    )
                    continue

                with open(target_path_real, 'r') as f:
                    results[path] = f.read()
            except Exception as e:
                results[path] = f'Read file <{path}> failed, error: ' + str(e)
        return str(results)

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

    @retry(max_attempts=MAX_CONTINUE_RUNS, delay=1.0)
    async def edit_file(self,
                        path: str = None,
                        instructions: str = None,
                        code_edit: str = None):
        try:
            with open(os.path.join(self.output_dir, path), 'r') as f:
                initial_code = f.read()
                response = self.client.chat.completions.create(
                    model=self.edit_file_config.diff_model,
                    messages=[{
                        'role':
                        'user',
                        'content':
                        (f'<instruction>{instructions}</instruction>\n'
                         f'<code>{initial_code}</code>\n'
                         f'<update>{code_edit}</update>')
                    }])
                merged_code = response.choices[0].message.content

            with open(os.path.join(self.output_dir, path), 'w') as f:
                f.write(merged_code)
            return f'Edit file <{path}> successfully.'
        except Exception as e:
            return f'Edit file <{path}> failed, error: ' + str(e)
