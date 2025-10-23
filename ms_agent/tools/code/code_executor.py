# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import socket
from pathlib import Path
from typing import Any, Dict, Optional, Union

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.tools.code.sandbox_manager import SandboxManagerFactory
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR
from ms_enclave.sandbox.manager import SandboxManager
from ms_enclave.sandbox.model import (DockerNotebookConfig,
                                      DockerSandboxConfig, ExecutionStatus,
                                      SandboxStatus, SandboxType)
from omegaconf import DictConfig

logger = get_logger()


def check_port_available(port: int, host: str = '127.0.0.1') -> bool:
    """
    Check if a port is available on the specified host.

    This method first tries to bind to the port directly (most reliable),
    and falls back to connection test if bind fails due to permissions.

    Args:
        port: Port number to check
        host: Host address to check (default: 127.0.0.1)

    Returns:
        True if port is available, False if occupied
    """
    # First try: bind to port directly (most reliable method)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True  # Bind successful, port is available
    except OSError as e:
        if e.errno == 98 or e.errno == 48:  # Address already in use
            return False  # Port is occupied
    except Exception as e:
        logger.warning(
            f'Bind test failed for port {port}, falling back to connection test: {e}'
        )

    # Second try: connection test (fallback method)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex((host, port))
            return result != 0  # 0 means connection successful, port is occupied
    except Exception as e:
        logger.warning(f'Error checking port {port}: {e}')
        return False  # Be conservative: assume occupied if we can't check reliably


def find_available_port(start_port: int = 8888,
                        max_attempts: int = 100,
                        host: str = '127.0.0.1') -> Optional[int]:
    """
    Find an available port starting from start_port.

    Args:
        start_port: Starting port number to check
        max_attempts: Maximum number of ports to try
        host: Host address to check

    Returns:
        Available port number, or None if no port found
    """
    for port in range(start_port, start_port + max_attempts):
        if check_port_available(port, host):
            logger.info(f'Found available port: {port}')
            return port

    logger.error(
        f'Could not find available port in range {start_port}-{start_port + max_attempts - 1}'
    )
    return None


class CodeExecutionTool(ToolBase):
    """
    Tool for executing Python code in an isolated Docker sandbox.

    Features:
    - Complete Docker container isolation
    - Resource limits (memory, CPU)
    - File operations
    - Data directory mounting for accessing input/output files
    """

    def __init__(self, config):
        super().__init__(config)
        self.manager: Optional[SandboxManager] = None
        self.sandbox_id: Optional[str] = None
        self._initialized = False
        self._original_port: Optional[int] = None
        self.sandbox_type: Optional[SandboxType] = None

        # Extract sandbox configuration
        self.sandbox_config = self._build_sandbox_config(config)

        self.exclude_func(getattr(config.tools, 'code_executor', None))

        logger.info('CodeExecutionTool initialized (ms-enclave based)')

    def _build_sandbox_config(
            self, config) -> Union[DockerNotebookConfig, DockerSandboxConfig]:
        """Build sandbox configuration from agent config"""

        # Get sandbox-specific config or use defaults
        if isinstance(config, DictConfig) and hasattr(
                config, 'tools') and hasattr(config.tools, 'code_executor'):
            sandbox_cfg = getattr(config.tools.code_executor, 'sandbox', {})
        else:
            sandbox_cfg = getattr(config, 'sandbox', {}) or getattr(
                config, 'tools', {}).get('sandbox', {})

        # Get output directory for data mounting
        output_dir = Path(getattr(config, 'output_dir', DEFAULT_OUTPUT_DIR))
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build volumes configuration
        volumes = {str(output_dir.absolute()): {'bind': '/data', 'mode': 'rw'}}

        # Build environment variables
        env_vars = {
            'DATA_DIR': '/data',
            'PYTHONUNBUFFERED': '1',
        }

        config_dict = {
            'volumes': volumes,
            'env_vars': env_vars,
        }
        if hasattr(sandbox_cfg, '__getitem__'):
            self.sandbox_type = sandbox_cfg.get('type',
                                                SandboxType.DOCKER_NOTEBOOK)

            config_dict.update({
                'image':
                sandbox_cfg.get('image', 'jupyter-kernel-gateway'),
                'command':
                sandbox_cfg.get('command', None),
                'ports':
                sandbox_cfg.get('ports', {}),
                'network':
                sandbox_cfg.get('network', 'bridge'),
                'memory_limit':
                sandbox_cfg.get('memory_limit', '2g'),
                'cpu_limit':
                sandbox_cfg.get('cpu_limit', 2.0),
                'network_enabled':
                sandbox_cfg.get('network_enabled', True),
                'privileged':
                sandbox_cfg.get('privileged', False),
                'remove_on_exit':
                sandbox_cfg.get('remove_on_exit', True),
                'timeout':
                sandbox_cfg.get('timeout', 30),
                'tools_config':
                sandbox_cfg.get('tools_config', {}),
                'working_dir':
                sandbox_cfg.get('working_dir', '/workspace'),
                'resource_limits':
                sandbox_cfg.get('resource_limits', {}),
            })

            if self.sandbox_type == SandboxType.DOCKER_NOTEBOOK:
                config_dict.update({
                    'host': sandbox_cfg.get('host', '127.0.0.1'),
                    'port': sandbox_cfg.get('port', 8888),
                    'token': sandbox_cfg.get('token', None),
                })

                # Store original port for retry logic
                self._original_port = config_dict['port']
                self._port_retry_enabled = sandbox_cfg.get(
                    'port_retry_enabled', True)
                self._max_port_retries = sandbox_cfg.get(
                    'max_port_retries', 10)

        logger.info(f'Sandbox config: type={self.sandbox_type}')

        if self.sandbox_type == SandboxType.DOCKER_NOTEBOOK:
            return DockerNotebookConfig(**config_dict)
        elif self.sandbox_type == SandboxType.DOCKER:
            return DockerSandboxConfig(**config_dict)
        else:
            raise ValueError(f'Unknown sandbox type: {self.sandbox_type}')

    async def connect(self) -> None:
        """Initialize sandbox manager and create sandbox instance with automatic port retry"""
        if self._initialized:
            logger.debug('Sandbox already initialized')
            return

        try:
            logger.info('Initializing sandbox manager...')

            # Create manager using factory
            self.manager = await SandboxManagerFactory.create_manager(
                self.config)
            await self.manager.start()

            logger.info('Creating sandbox instance...')

            # Try to create sandbox with port retry logic
            retry_count = 0
            max_retries = self._max_port_retries if self._port_retry_enabled else 1
            last_error = None

            while retry_count < max_retries:
                try:
                    self.sandbox_id = await self.manager.create_sandbox(
                        sandbox_type=self.sandbox_type,
                        config=self.sandbox_config)

                    logger.info(f'Sandbox created: {self.sandbox_id}')

                    # Wait for sandbox to be ready
                    await self._wait_for_sandbox_ready()

                    self._initialized = True
                    logger.info('Sandbox is ready for code execution')
                    return

                except Exception as e:
                    error_msg = str(e).lower()
                    last_error = e

                    # Check if it's a port conflict error
                    is_port_conflict = any(keyword in error_msg
                                           for keyword in [
                                               'address already in use',
                                               'port is already allocated',
                                               'bind: address already in use',
                                               'port already in use'
                                           ])

                    if is_port_conflict and self._port_retry_enabled and retry_count < (
                            max_retries - 1):
                        retry_count += 1
                        logger.warning(
                            f'Port conflict detected (attempt {retry_count}/{max_retries}): {e}'
                        )

                        # Try to find a new available port
                        if self.sandbox_type == SandboxType.DOCKER_NOTEBOOK:
                            new_port = find_available_port(
                                start_port=self.sandbox_config.port + 1,
                                max_attempts=100,
                                host=self.sandbox_config.host)

                            if new_port:
                                logger.info(
                                    f'Retrying with new port: {new_port} (was {self.sandbox_config.port})'
                                )
                                # Update the config with new port
                                self.sandbox_config.port = new_port

                                # Clean up failed sandbox if it was created
                                if self.sandbox_id:
                                    try:
                                        await self.manager.delete_sandbox(
                                            self.sandbox_id)
                                        self.sandbox_id = None
                                    except Exception as cleanup_error:
                                        logger.warning(
                                            f'Failed to cleanup sandbox: {cleanup_error}'
                                        )

                                # Wait a bit before retry
                                await asyncio.sleep(1)
                                continue
                            else:
                                logger.error(
                                    'Could not find available port for retry')
                                raise RuntimeError(
                                    f'Port conflict and no available ports found: {e}'
                                )
                        else:
                            # For non-notebook sandbox, just retry
                            logger.info(
                                f'Retrying sandbox creation (attempt {retry_count}/{max_retries})...'
                            )
                            await asyncio.sleep(1)
                            continue
                    else:
                        # Not a port conflict or retries exhausted
                        raise

            logger.error(
                f'Failed to create sandbox after {max_retries} attempts')
            raise RuntimeError(
                f'Sandbox initialization failed after {max_retries} attempts: {last_error}'
            )

        except Exception as e:
            logger.error(f'Failed to initialize sandbox: {e}', exc_info=True)
            raise RuntimeError(f'Sandbox initialization failed: {e}')

    async def cleanup(self) -> None:
        """Clean up sandbox resources"""
        if not self._initialized:
            return

        try:
            logger.info('Cleaning up sandbox resources...')

            if self.manager and self.sandbox_id:
                await self.manager.delete_sandbox(self.sandbox_id)
                await self.manager.stop()

            self._initialized = False
            logger.info('Sandbox cleanup completed')

        except Exception as e:
            logger.error(f'Error during sandbox cleanup: {e}', exc_info=True)

    async def get_tools(self) -> Dict[str, Any]:
        """Return tool definitions for LLM"""
        tools = {
            'code_executor': [
                Tool(
                    tool_name='notebook_executor',
                    server_name='code_executor',
                    description=
                    ('Execute Python code in an isolated Docker sandbox with state '
                     'persistence in a Jupyter kernel environment. Variables, imports, and '
                     'data are preserved across multiple calls within the same session. '
                     'Supports pandas, numpy, matplotlib, seaborn for data analysis. '
                     'Data files in the output directory are accessible at /data/ path. '
                     'Use print() to output results.'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type':
                                'string',
                                'description':
                                ('Python code to execute. Can access previously defined variables. '
                                 'Data files are at /data/ (e.g., pd.read_csv(\'/data/file.csv\')). '
                                 'Use print() for output.')
                            },
                            'description': {
                                'type':
                                'string',
                                'description':
                                'Brief description of what the code does'
                            },
                            'timeout': {
                                'type': 'integer',
                                'minimum': 1,
                                'maximum': 600,
                                'description': 'Execution timeout in seconds',
                                'default': 60
                            }
                        },
                        'required': ['code'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='python_executor',
                    server_name='code_executor',
                    description=
                    ('Execute Python code in an isolated environment. '
                     'Supports pandas, numpy, matplotlib, seaborn and other libraries you need for data analysis. '
                     'Data files in the output directory are accessible at /data/ path. '
                     'Use print() to output results.'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type': 'string',
                                'description': 'Python code to execute'
                            },
                            'description': {
                                'type':
                                'string',
                                'description':
                                'Brief description of what the code does'
                            },
                            'timeout': {
                                'type': 'integer',
                                'description': 'Execution timeout in seconds',
                                'default': 30
                            }
                        },
                        'required': ['code'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='shell_executor',
                    server_name='code_executor',
                    description=
                    ('Execute shell commands in an isolated environment using bash. '
                     'Supports basic shell operations like ls, cd, mkdir, rm, etc. '
                     'Data files in the output directory are accessible at /data/ path. '
                     ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'command': {
                                'type': 'string',
                                'description': 'Shell command to execute'
                            },
                            'timeout': {
                                'type': 'integer',
                                'description': 'Execution timeout in seconds',
                                'default': 30
                            }
                        },
                        'required': ['command'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='file_operation',
                    server_name='code_executor',
                    description=
                    'Perform file operations like read, write, delete, and list files',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'operation': {
                                'type':
                                'string',
                                'description':
                                'Type of file operation to perform',
                                'enum': [
                                    'create', 'read', 'write', 'delete',
                                    'list', 'exists'
                                ]
                            },
                            'file_path': {
                                'type': 'string',
                                'description': 'Path to the file or directory'
                            },
                            'content': {
                                'type':
                                'string',
                                'description':
                                'Content to write to file (only for write operation)'
                            },
                            'encoding': {
                                'type': 'string',
                                'description': 'File encoding',
                                'default': 'utf-8'
                            }
                        },
                        'required': ['operation', 'file_path'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='reset_sandbox',
                    server_name='code_executor',
                    description=
                    ('Reset the sandbox state by restarting the kernel. '
                     'All variables, imports, and session state will be cleared.'
                     ),
                    parameters={
                        'type': 'object',
                        'properties': {},
                        'required': [],
                        'additionalProperties': False
                    },
                ),
                Tool(
                    tool_name='get_sandbox_info',
                    server_name='code_executor',
                    description='Get current sandbox status and information',
                    parameters={
                        'type': 'object',
                        'properties': {},
                        'required': [],
                        'additionalProperties': False
                    },
                )
            ]
        }

        return {
            'code_executor': [
                t for t in tools['code_executor']
                if t['tool_name'] not in self.exclude_functions
            ]
        }

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        """Route tool calls to appropriate methods"""
        if not self._initialized:
            await self.connect()

        try:
            method = getattr(self, tool_name)
            return await method(**tool_args)
        except AttributeError:
            return json.dumps(
                {
                    'success': False,
                    'error': f'Unknown tool: {tool_name}'
                },
                indent=2)
        except Exception as e:
            logger.error(
                f'Tool execution error ({tool_name}): {e}', exc_info=True)
            return json.dumps(
                {
                    'success': False,
                    'error': f'Tool execution error: {str(e)}'
                },
                indent=2)

    async def notebook_executor(self,
                                code: str,
                                description: str = '',
                                timeout: Optional[int] = None) -> str:
        """
        Execute Python code in the sandbox using notebook_executor.

        Args:
            code: Python code to execute
            description: Description of what the code does
            timeout: Execution timeout in seconds

        Returns:
            JSON string with execution results
        """
        try:
            logger.info(f'Executing code: {description or code[:50]}...')

            # Execute via notebook_executor (maintains state)
            result = await self.manager.execute_tool(
                sandbox_id=self.sandbox_id,
                tool_name='notebook_executor',
                parameters={
                    'code': code,
                    'timeout': timeout or 60
                })

            success = result.status == ExecutionStatus.SUCCESS

            if success:
                logger.info('Code executed successfully')
            else:
                logger.warning(f'Code execution failed: {result.error}')

            return json.dumps(
                {
                    'success': success,
                    'description': description,
                    'output': result.output or '',
                    'error': result.error if result.error else None
                },
                indent=2)

        except Exception as e:
            logger.error(f'Execute python failed: {e}', exc_info=True)
            return json.dumps(
                {
                    'success': False,
                    'description': description,
                    'error': str(e)
                },
                indent=2)

    async def python_executor(self,
                              code: str,
                              description: str = '',
                              timeout: Optional[int] = None) -> str:
        """
        Execute Python code in the sandbox.

        Args:
            code: Python code to execute
            description: Description of what the code does
            timeout: Execution timeout in seconds

        Returns:
            JSON string with execution results
        """
        try:
            logger.info(f'Executing code: {description or code[:50]}...')

            # Execute via python_executor (maintains state)
            result = await self.manager.execute_tool(
                sandbox_id=self.sandbox_id,
                tool_name='python_executor',
                parameters={
                    'code': code,
                    'timeout': timeout or 60
                })

            success = result.status == ExecutionStatus.SUCCESS

            if success:
                logger.info('Code executed successfully')
            else:
                logger.warning(f'Code execution failed: {result.error}')

            return json.dumps(
                {
                    'success': success,
                    'description': description,
                    'output': result.output or '',
                    'error': result.error if result.error else None
                },
                indent=2)

        except Exception as e:
            logger.error(f'Execute python failed: {e}', exc_info=True)
            return json.dumps(
                {
                    'success': False,
                    'description': description,
                    'error': str(e)
                },
                indent=2)

    async def shell_executor(self,
                             command: str,
                             timeout: Optional[int] = None) -> str:
        """
        Execute shell commands in the sandbox.

        Args:
            command: Shell command to execute
            timeout: Execution timeout in seconds

        Returns:
            JSON string with execution results
        """
        try:
            logger.info(f'Executing command: {command[:50]}...')

            # Execute via shell_executor
            result = await self.manager.execute_tool(
                sandbox_id=self.sandbox_id,
                tool_name='shell_executor',
                parameters={
                    'command': command,
                    'timeout': timeout or 60
                })
            success = result.status == ExecutionStatus.SUCCESS

            if success:
                logger.info('Command executed successfully')
            else:
                logger.warning(f'Command execution failed: {result.error}')

            return json.dumps(
                {
                    'success': success,
                    'output': result.output or '',
                    'error': result.error if result.error else None
                },
                indent=2)

        except Exception as e:
            logger.error(f'Execute shell failed: {e}', exc_info=True)
            return json.dumps({'success': False, 'error': str(e)}, indent=2)

    async def file_operation(self,
                             operation: str,
                             file_path: str,
                             content: Optional[str] = None,
                             encoding: Optional[str] = 'utf-8') -> str:
        """
        Perform file operations like read, write, delete, and list files in the sandbox.

        Args:
            operation: Type of file operation to perform
            file_path: Path to the file in sandbox
            content: Content to write to file (only for write operation)
            encoding: File encoding

        Returns:
            JSON string with file content
        """
        try:
            result = await self.manager.execute_tool(
                sandbox_id=self.sandbox_id,
                tool_name='file_operation',
                parameters={
                    'operation': operation,
                    'file_path': file_path,
                    'content': content,
                    'encoding': encoding
                })

            success = result.status == ExecutionStatus.SUCCESS

            if success:
                logger.info(
                    f'File operation {operation} successful for {file_path}')
            else:
                logger.warning(
                    f'File operation {operation} failed for {file_path}: {result.error}'
                )

            return json.dumps(
                {
                    'success': success,
                    'file_path': file_path,
                    'output': result.output if success else '',
                    'error': result.error if result.error else None
                },
                indent=2)

        except Exception as e:
            logger.error(f'Read file failed: {e}', exc_info=True)
            return json.dumps(
                {
                    'success': False,
                    'file_path': file_path,
                    'error': str(e)
                },
                indent=2)

    async def reset_sandbox(self) -> str:
        """
        Reset the sandbox by recreating it.
        This clears all variables and session state.

        Returns:
            JSON string with result
        """
        try:
            logger.info('Resetting sandbox...')

            # Delete old sandbox
            await self.manager.delete_sandbox(self.sandbox_id)

            # Create new sandbox
            self.sandbox_id = await self.manager.create_sandbox(
                sandbox_type=SandboxType.DOCKER_NOTEBOOK,
                config=self.sandbox_config)

            # Wait for it to be ready
            await self._wait_for_sandbox_ready()

            logger.info(f'Sandbox reset complete: {self.sandbox_id}')

            return json.dumps(
                {
                    'success': True,
                    'message':
                    'Sandbox reset successfully. All variables and state cleared.',
                    'new_sandbox_id': self.sandbox_id
                },
                indent=2)

        except Exception as e:
            logger.error(f'Reset sandbox failed: {e}', exc_info=True)
            return json.dumps({'success': False, 'error': str(e)}, indent=2)

    async def get_sandbox_info(self) -> str:
        """
        Get current sandbox information.

        Returns:
            JSON string with sandbox info
        """
        try:
            info = await self.manager.get_sandbox_info(self.sandbox_id)

            if info:
                return json.dumps(
                    {
                        'success': True,
                        'sandbox_id': info.id,
                        'status': info.status.value,
                        'type': info.type,
                        'created_at': str(info.created_at),
                        'updated_at': str(info.updated_at),
                        'available_tools': list(info.available_tools.keys()),
                        'config': {
                            'memory_limit': self.sandbox_config.memory_limit,
                            'cpu_limit': self.sandbox_config.cpu_limit,
                            'timeout': self.sandbox_config.timeout
                        }
                    },
                    indent=2,
                    default=str)
            else:
                return json.dumps(
                    {
                        'success': False,
                        'error': 'Sandbox info not available'
                    },
                    indent=2)

        except Exception as e:
            logger.error(f'Get sandbox info failed: {e}', exc_info=True)
            return json.dumps({'success': False, 'error': str(e)}, indent=2)

    async def _wait_for_sandbox_ready(self, max_wait: int = 60) -> None:
        """
        Wait for sandbox to become ready.

        Args:
            max_wait: Maximum seconds to wait

        Raises:
            TimeoutError: If sandbox doesn't become ready in time
            RuntimeError: If sandbox enters error state
        """
        logger.info('Waiting for sandbox to be ready...')

        for i in range(max_wait):
            info = await self.manager.get_sandbox_info(self.sandbox_id)

            if info.status == SandboxStatus.RUNNING:
                logger.info('Sandbox is running and ready')
                return
            elif info.status == SandboxStatus.ERROR:
                error_msg = info.metadata.get('error', 'Unknown error')
                raise RuntimeError(f'Sandbox failed to start: {error_msg}')

            if i % 5 == 0:
                logger.debug(
                    f'Waiting for sandbox... ({i}/{max_wait}s, status={info.status.value})'
                )

            await asyncio.sleep(1)

        raise TimeoutError(
            f'Sandbox failed to become ready within {max_wait} seconds')
