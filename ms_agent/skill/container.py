# Copyright (c) ModelScope Contributors. All rights reserved.
"""
Skill Execution Container

Provides a unified, secure execution environment for skills using EnclaveSandbox.
Supports multiple languages (Python, Shell, JavaScript) with Docker-based isolation.
Cross-platform support (Mac/Linux/Windows) with RCE prevention.

Execution modes:
- use_sandbox=True: Execute in Docker sandbox (default, recommended for untrusted code)
- use_sandbox=False: Execute locally with security checks (for trusted code or no Docker)
"""
import asyncio
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from ms_agent.utils.logger import get_logger

logger = get_logger()

# Security: Patterns to detect potentially dangerous code (sandbox mode)
# Note: These are checked only in sandbox mode for stricter isolation
DANGEROUS_PATTERNS = [
    r'os\.system\s*\(',  # os.system
    r'subprocess\.call\s*\([^)]*shell\s*=\s*True',  # subprocess with shell=True
    r'open\s*\([^)]*["\']\/etc',  # Reading system files
    r'rm\s+-rf\s+\/',  # Dangerous rm commands
    r'chmod\s+777',  # Dangerous chmod
    r'curl\s+.*\|\s*sh',  # Piped curl execution
    r'wget\s+.*\|\s*sh',  # Piped wget execution
]

# Additional patterns for local execution (stricter but reasonable)
# Note: eval/exec are allowed as they're commonly used in generated code
LOCAL_DANGEROUS_PATTERNS = DANGEROUS_PATTERNS + [
    r'shutil\.rmtree\s*\([^)]*["\']/',  # Removing root paths
    r'pathlib\.Path\s*\([^)]*["\']/',  # Accessing root paths
]

# Allowed file extensions for local script execution
ALLOWED_SCRIPT_EXTENSIONS = {'.py', '.sh', '.bash', '.js', '.mjs'}


class ExecutorType(Enum):
    """Supported executor types for skill execution."""
    PYTHON_SCRIPT = 'python_script'
    PYTHON_CODE = 'python_code'
    PYTHON_FUNCTION = 'python_function'
    SHELL = 'shell'
    JAVASCRIPT = 'javascript'


class ExecutionStatus(Enum):
    """Execution status codes."""
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'
    TIMEOUT = 'timeout'
    CANCELLED = 'cancelled'
    SECURITY_BLOCKED = 'security_blocked'


@dataclass
class ExecutionInput:
    """
    Input specification for skill execution.

    Attributes:
        args: Command line arguments or positional parameters.
        kwargs: Keyword arguments for function calls.
        env_vars: Environment variables to set during execution.
        input_files: Dict of input files {name: path or content}.
        stdin: Standard input content.
        working_dir: Working directory for execution.
        requirements: Python packages to install before execution.
    """
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    env_vars: Dict[str, str] = field(default_factory=dict)
    input_files: Dict[str, Union[str, Path]] = field(default_factory=dict)
    stdin: Optional[str] = None
    working_dir: Optional[Path] = None
    requirements: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'args': self.args,
            'kwargs': self.kwargs,
            'env_vars': self.env_vars,
            'input_files': {k: str(v)
                            for k, v in self.input_files.items()},
            'stdin': self.stdin,
            'working_dir': str(self.working_dir) if self.working_dir else None,
            'requirements': self.requirements,
        }


@dataclass
class ExecutionOutput:
    """
    Output specification for skill execution.

    Attributes:
        return_value: Return value from function execution.
        stdout: Standard output content.
        stderr: Standard error content.
        exit_code: Process exit code.
        output_files: Dict of output files {name: path}.
        artifacts: Any generated artifacts (data, objects, etc.).
        duration_ms: Execution duration in milliseconds.
    """
    return_value: Any = None
    stdout: str = ''
    stderr: str = ''
    exit_code: int = 0
    output_files: Dict[str, Path] = field(default_factory=dict)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'return_value':
            str(self.return_value) if self.return_value else None,
            'stdout': self.stdout,
            'stderr': self.stderr,
            'exit_code': self.exit_code,
            'output_files': {k: str(v)
                             for k, v in self.output_files.items()},
            'artifacts': list(self.artifacts.keys()),
            'duration_ms': self.duration_ms,
        }


@dataclass
class ExecutionRecord:
    """
    A single execution record in the spec log.

    Attributes:
        execution_id: Unique identifier for this execution.
        skill_id: The skill being executed.
        executor_type: Type of executor used.
        script_path: Path to the script (if applicable).
        function_name: Name of the function (if applicable).
        input_spec: Input specification.
        output_spec: Output specification.
        status: Execution status.
        start_time: Execution start time.
        end_time: Execution end time.
        error_message: Error message if failed.
        sandbox_used: Whether sandbox was used for execution.
    """
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    skill_id: str = ''
    executor_type: ExecutorType = ExecutorType.PYTHON_SCRIPT
    script_path: Optional[str] = None
    function_name: Optional[str] = None
    input_spec: ExecutionInput = field(default_factory=ExecutionInput)
    output_spec: ExecutionOutput = field(default_factory=ExecutionOutput)
    status: ExecutionStatus = ExecutionStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    sandbox_used: bool = True

    def to_markdown(self) -> str:
        """Convert execution record to markdown format."""
        lines = [
            f'### Execution: `{self.execution_id}`',
            '',
            f'- **Skill ID**: `{self.skill_id}`',
            f'- **Executor**: `{self.executor_type.value}`',
            f'- **Status**: `{self.status.value}`',
            f'- **Sandbox**: `{"Yes" if self.sandbox_used else "No"}`',
        ]

        if self.script_path:
            lines.append(f'- **Script**: `{self.script_path}`')
        if self.function_name:
            lines.append(f'- **Function**: `{self.function_name}`')

        if self.start_time:
            lines.append(f'- **Start Time**: `{self.start_time.isoformat()}`')
        if self.end_time:
            lines.append(f'- **End Time**: `{self.end_time.isoformat()}`')

        lines.append(f'- **Duration**: `{self.output_spec.duration_ms:.2f}ms`')

        # Input section
        lines.extend(['', '#### Input', ''])
        if self.input_spec.args:
            lines.append(f'- **Args**: `{self.input_spec.args}`')
        if self.input_spec.kwargs:
            lines.append(f'- **Kwargs**: `{self.input_spec.kwargs}`')
        if self.input_spec.input_files:
            lines.append('- **Input Files**:')
            for name, path in self.input_spec.input_files.items():
                lines.append(f'  - `{name}`: `{path}`')
        if self.input_spec.requirements:
            lines.append(
                f'- **Requirements**: `{self.input_spec.requirements}`')

        # Output section
        lines.extend(['', '#### Output', ''])
        lines.append(f'- **Exit Code**: `{self.output_spec.exit_code}`')

        if self.output_spec.stdout:
            stdout_preview = self.output_spec.stdout[:1000]
            lines.extend(['', '**stdout**:', '```', stdout_preview, '```'])
        if self.output_spec.stderr:
            stderr_preview = self.output_spec.stderr[:1000]
            lines.extend(['', '**stderr**:', '```', stderr_preview, '```'])
        if self.output_spec.output_files:
            lines.append('- **Output Files**:')
            for name, path in self.output_spec.output_files.items():
                lines.append(f'  - `{name}`: `{path}`')

        if self.error_message:
            lines.extend(
                ['', '#### Error', '', f'```\n{self.error_message}\n```'])

        lines.append('')
        return '\n'.join(lines)


@dataclass
class ExecutionSpec:
    """
    Specification log for tracking execution flow across skills.

    Attributes:
        spec_id: Unique identifier for this spec.
        title: Title of the execution spec.
        description: Description of the execution flow.
        records: List of execution records.
        created_at: Creation timestamp.
        upstream_outputs: Outputs from upstream skills available as inputs.
    """
    spec_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = 'Skill Execution Spec'
    description: str = ''
    records: List[ExecutionRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    upstream_outputs: Dict[str, ExecutionOutput] = field(default_factory=dict)

    def add_record(self, record: ExecutionRecord):
        """Add an execution record to the spec."""
        self.records.append(record)

    def get_output(self, execution_id: str) -> Optional[ExecutionOutput]:
        """Get output from a specific execution by ID."""
        for record in self.records:
            if record.execution_id == execution_id:
                return record.output_spec
        return None

    def link_upstream(self, skill_id: str, output: ExecutionOutput):
        """Link upstream skill output for downstream consumption."""
        self.upstream_outputs[skill_id] = output

    def to_markdown(self) -> str:
        """Convert entire spec to markdown format."""
        lines = [
            f'# {self.title}',
            '',
            f'**Spec ID**: `{self.spec_id}`',
            f'**Created**: `{self.created_at.isoformat()}`',
            '',
        ]

        if self.description:
            lines.extend([self.description, ''])

        # Summary
        total = len(self.records)
        success = sum(1 for r in self.records
                      if r.status == ExecutionStatus.SUCCESS)
        failed = sum(1 for r in self.records
                     if r.status == ExecutionStatus.FAILED)
        blocked = sum(1 for r in self.records
                      if r.status == ExecutionStatus.SECURITY_BLOCKED)

        lines.extend([
            '## Summary',
            '',
            f'- **Total Executions**: {total}',
            f'- **Successful**: {success}',
            f'- **Failed**: {failed}',
            f'- **Security Blocked**: {blocked}',
            '',
            '---',
            '',
            '## Execution Records',
            '',
        ])

        for record in self.records:
            lines.append(record.to_markdown())
            lines.append('---')
            lines.append('')

        return '\n'.join(lines)

    def save(self, output_path: Union[str, Path]):
        """Save spec to markdown file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(self.to_markdown())
        logger.info(f'Execution spec saved to: {output_path}')


class SkillContainer:
    """
    Secure container for executing skills.

    Supports two execution modes:
    - use_sandbox=True: Execute in Docker sandbox via ms-enclave (recommended for untrusted code)
    - use_sandbox=False: Execute locally with security checks (for trusted code or no Docker)

    Features:
    - Docker-based isolation via ms-enclave
    - Python scripts, Python code, shell commands, and JavaScript support
    - Cross-platform support (Mac/Linux/Windows)
    - RCE prevention and security checks
    """

    # Container paths for sandbox (following AgentSkill pattern)
    SANDBOX_ROOT = '/sandbox'
    SANDBOX_OUTPUT_DIR = '/sandbox/outputs'
    SANDBOX_WORK_DIR = '/sandbox/scripts'

    def __init__(self,
                 workspace_dir: Optional[Union[str, Path]] = None,
                 timeout: int = 300,
                 image: str = 'python:3.11-slim',
                 memory_limit: str = '512m',
                 enable_security_check: bool = True,
                 network_enabled: bool = False,
                 use_sandbox: bool = True):
        """
        Initialize the skill container.

        Args:
            workspace_dir: Host working directory for I/O. Creates temp dir if None.
            timeout: Default execution timeout in seconds.
            image: Docker image for sandbox execution.
            memory_limit: Memory limit for sandbox container.
            enable_security_check: Whether to check code for dangerous patterns.
            network_enabled: Whether to enable network in sandbox (disabled by default for security).
            use_sandbox: Whether to use Docker sandbox (True) or local execution (False).
        """
        # Ensure workspace_dir is an absolute path (required by Docker)
        if workspace_dir:
            self.workspace_dir = Path(workspace_dir).resolve()
        else:
            self.workspace_dir = Path(
                tempfile.mkdtemp(prefix='skill_container_')).resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        self.timeout = timeout
        self.image = image
        self.memory_limit = memory_limit
        self.enable_security_check = enable_security_check
        self.network_enabled = network_enabled
        self.use_sandbox = use_sandbox
        self.spec = ExecutionSpec()

        # Host directories for I/O management (only outputs, scripts, logs)
        self.output_dir = self.workspace_dir / 'outputs'
        self.scripts_dir = self.workspace_dir / 'scripts'
        self.logs_dir = self.workspace_dir / 'logs'
        self.output_dir.mkdir(exist_ok=True)
        self.scripts_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)

        # Sandbox instance (lazy initialization)
        self._sandbox = None

        # Skill directories to mount in sandbox
        self._skill_dirs: Dict[str, str] = {}

        # Warn about local execution risks
        if not self.use_sandbox:
            logger.warning(
                'SkillContainer running in LOCAL mode (use_sandbox=False). '
                'Scripts will execute directly on this machine. '
                'Ensure you trust the code being executed!')

        logger.info(f'SkillContainer initialized at: {self.workspace_dir} '
                    f'[mode: {"sandbox" if self.use_sandbox else "local"}]')

    def _get_sandbox(self):
        """
        Get or create EnclaveSandbox instance with volume mounts.

        Volume mapping follows AgentSkill pattern:
        - workspace_dir -> /sandbox (rw mode for full access)
        - Additional skill directories are mounted to /sandbox/skills/
        """
        if self._sandbox is None:
            from ms_agent.sandbox.sandbox import EnclaveSandbox

            # Mount entire workspace to /sandbox following AgentSkill pattern
            # This allows scripts to access inputs/, outputs/, scripts/ subdirs
            volumes = [
                (str(self.workspace_dir.resolve()), self.SANDBOX_ROOT, 'rw'),
            ]

            # Add additional skill directory mounts
            for skill_id, skill_dir in self._skill_dirs.items():
                safe_id = skill_id.replace('@', '_').replace('/', '_')
                sandbox_path = f'{self.SANDBOX_ROOT}/skills/{safe_id}'
                volumes.append(
                    (str(Path(skill_dir).resolve()), sandbox_path, 'ro'))

            self._sandbox = EnclaveSandbox(
                image=self.image,
                memory_limit=self.memory_limit,
                volumes=volumes,
            )
        return self._sandbox

    def mount_skill_directory(self, skill_id: str, skill_dir: Union[str,
                                                                    Path]):
        """
        Mount a skill directory for sandbox access.

        Args:
            skill_id: Unique identifier for the skill.
            skill_dir: Path to the skill directory.
        """
        self._skill_dirs[skill_id] = str(Path(skill_dir).resolve())
        # Reset sandbox to recreate with new mount
        self._sandbox = None

    def get_skill_sandbox_path(self, skill_id: str) -> str:
        """
        Get the sandbox path for a mounted skill directory.

        Args:
            skill_id: The skill identifier.

        Returns:
            Path inside sandbox where skill is mounted.
        """
        safe_id = skill_id.replace('@', '_').replace('/', '_')
        return f'{self.SANDBOX_ROOT}/skills/{safe_id}'

    def _security_check(self,
                        code: str,
                        is_local: bool = False) -> tuple[bool, str]:
        """
        Check code for potentially dangerous patterns.

        Args:
            code: Code string to check.
            is_local: If True, use stricter patterns for local execution.

        Returns:
            Tuple of (is_safe, reason).
        """
        if not self.enable_security_check:
            return True, ''

        # Use stricter patterns for local execution
        patterns = LOCAL_DANGEROUS_PATTERNS if is_local else DANGEROUS_PATTERNS

        for pattern in patterns:
            if re.search(pattern, code, re.IGNORECASE):
                return False, f'Dangerous pattern detected: {pattern}'

        return True, ''

    def _validate_path_in_workspace(self, path: Path) -> bool:
        """
        Validate that a path is within the workspace directory.

        Security measure for local execution to prevent path traversal.

        Args:
            path: Path to validate.

        Returns:
            True if path is within workspace, False otherwise.
        """
        try:
            resolved = path.resolve()
            return str(resolved).startswith(str(self.workspace_dir.resolve()))
        except (OSError, ValueError):
            return False

    def _validate_script_extension(self, script_path: Path) -> bool:
        """
        Validate that script has an allowed extension.

        Args:
            script_path: Path to the script file.

        Returns:
            True if extension is allowed, False otherwise.
        """
        return script_path.suffix.lower() in ALLOWED_SCRIPT_EXTENSIONS

    def _collect_output_files(self) -> Dict[str, Path]:
        """Collect output files from output directory."""
        outputs = {}
        if self.output_dir.exists():
            for f in self.output_dir.iterdir():
                if f.is_file():
                    outputs[f.name] = f
        return outputs

    def _create_record(self,
                       skill_id: str,
                       executor_type: ExecutorType,
                       input_spec: ExecutionInput,
                       script_path: str = None,
                       function_name: str = None,
                       sandbox_used: bool = None) -> ExecutionRecord:
        """Create a new execution record."""
        return ExecutionRecord(
            skill_id=skill_id,
            executor_type=executor_type,
            script_path=script_path,
            function_name=function_name,
            input_spec=input_spec,
            status=ExecutionStatus.PENDING,
            sandbox_used=sandbox_used
            if sandbox_used is not None else self.use_sandbox)

    # -------------------------------------------------------------------------
    # Local Execution Helpers (for use_sandbox=False mode)
    # -------------------------------------------------------------------------

    def _local_run_subprocess(self,
                              cmd: List[str],
                              env: Dict[str, str] = None,
                              cwd: Path = None,
                              stdin_input: str = None) -> tuple[str, str, int]:
        """
        Run subprocess locally with security restrictions.

        Cross-platform support with timeout and resource limits.

        Args:
            cmd: Command list to execute.
            env: Environment variables.
            cwd: Working directory.
            stdin_input: Input to pass to stdin.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        # Setup environment
        run_env = os.environ.copy()
        run_env['SKILL_OUTPUT_DIR'] = str(self.output_dir)
        if env:
            run_env.update(env)

        # Use workspace as default cwd
        work_dir = cwd or self.workspace_dir

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(work_dir),
                env=run_env,
                stdin=subprocess.PIPE if stdin_input else None,
                input=stdin_input,
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return '', f'Execution timed out after {self.timeout}s', -1
        except Exception as e:
            return '', str(e), -1

    def _get_python_executable(self) -> str:
        """Get the Python executable for the current platform."""
        return sys.executable

    def _get_shell_executable(self) -> List[str]:
        """Get the shell executable for the current platform."""
        if platform.system() == 'Windows':
            return ['cmd', '/c']
        else:
            return ['/bin/sh', '-c']

    def _get_node_executable(self) -> str:
        """Get the Node.js executable for the current platform."""
        if platform.system() == 'Windows':
            return 'node.exe'
        return 'node'

    async def _local_install_requirements(
            self, requirements: List[str]) -> tuple[bool, str]:
        """
        Install Python requirements locally using pip.

        Args:
            requirements: List of packages to install.

        Returns:
            Tuple of (success, error_message).
        """
        if not requirements:
            return True, ''

        try:
            cmd = [
                self._get_python_executable(), '-m', 'pip', 'install',
                '--quiet', '--disable-pip-version-check'
            ] + requirements

            stdout, stderr, exit_code = self._local_run_subprocess(cmd)

            if exit_code != 0:
                logger.warning(f'Failed to install requirements: {stderr}')
                return False, stderr

            logger.info(f'Installed requirements: {requirements}')
            return True, ''
        except Exception as e:
            logger.error(f'Error installing requirements: {e}')
            return False, str(e)

    async def _local_execute_python_code(
            self, code: str,
            input_spec: ExecutionInput) -> tuple[str, str, int]:
        """
        Execute Python code locally.

        Args:
            code: Python code to execute.
            input_spec: Input specification.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        # Install requirements first if any
        if input_spec.requirements:
            success, error = await self._local_install_requirements(
                input_spec.requirements)
            if not success:
                return '', f'Failed to install requirements: {error}', -1

        # Write code to temp file
        script_file = self.scripts_dir / f'_temp_{uuid.uuid4().hex[:8]}.py'
        try:
            # Generate environment setup
            env_setup = self._generate_local_env_setup(input_spec)
            full_code = env_setup + '\n' + code

            with open(script_file, 'w', encoding='utf-8') as f:
                f.write(full_code)

            # Build command
            cmd = [self._get_python_executable(), str(script_file)]
            cmd.extend([str(arg) for arg in input_spec.args])

            # Use working_dir from input_spec for proper resource access
            cwd = input_spec.working_dir if input_spec.working_dir else None

            stdout, stderr, exit_code = self._local_run_subprocess(
                cmd,
                env=input_spec.env_vars,
                cwd=cwd,
                stdin_input=input_spec.stdin)

            # Keep script in scripts folder for logging/debugging
            return stdout, stderr, exit_code
        except Exception as e:
            logger.error(f'Local Python execution failed: {e}')
            raise

    async def _local_execute_shell(
            self, command: str,
            input_spec: ExecutionInput) -> tuple[str, str, int]:
        """
        Execute shell command locally.

        Args:
            command: Shell command to execute.
            input_spec: Input specification.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        shell_exec = self._get_shell_executable()

        # Build full command with environment exports
        if platform.system() == 'Windows':
            # Windows: use set for environment
            env_cmds = [f'set {k}={v}' for k, v in input_spec.env_vars.items()]
            full_cmd = ' && '.join(env_cmds
                                   + [command]) if env_cmds else command
            cmd = shell_exec + [full_cmd]
        else:
            # Unix: use export
            env_cmds = [
                f"export {k}='{v}'" for k, v in input_spec.env_vars.items()
            ]
            full_cmd = ' && '.join(env_cmds
                                   + [command]) if env_cmds else command
            cmd = shell_exec + [full_cmd]

        # Use working_dir from input_spec for proper resource access
        cwd = input_spec.working_dir if input_spec.working_dir else None

        return self._local_run_subprocess(
            cmd,
            env=input_spec.env_vars,
            cwd=cwd,
            stdin_input=input_spec.stdin)

    async def _local_execute_javascript(
            self, js_code: str,
            input_spec: ExecutionInput) -> tuple[str, str, int]:
        """
        Execute JavaScript code locally via Node.js.

        Args:
            js_code: JavaScript code to execute.
            input_spec: Input specification.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        # Write code to temp file
        script_file = self.scripts_dir / f'_temp_{uuid.uuid4().hex[:8]}.js'
        try:
            # Generate environment setup
            env_setup = self._generate_local_js_env_setup(input_spec)
            full_code = env_setup + '\n' + js_code

            with open(script_file, 'w', encoding='utf-8') as f:
                f.write(full_code)

            # Build command
            cmd = [self._get_node_executable(), str(script_file)]
            cmd.extend([str(arg) for arg in input_spec.args])

            # Use working_dir from input_spec for proper resource access
            cwd = input_spec.working_dir if input_spec.working_dir else None

            # Keep script in scripts folder for logging/debugging
            return self._local_run_subprocess(
                cmd,
                env=input_spec.env_vars,
                cwd=cwd,
                stdin_input=input_spec.stdin)
        except Exception as e:
            logger.error(f'Local JavaScript execution failed: {e}')
            raise

    def _generate_local_env_setup(self, input_spec: ExecutionInput) -> str:
        """Generate Python code to setup environment for local execution."""
        lines = [
            'import os',
            'import sys',
            '',
            '# Setup environment for local execution',
            f"os.environ['SKILL_OUTPUT_DIR'] = {repr(str(self.output_dir))}",
            f"os.environ['SKILL_LOGS_DIR'] = {repr(str(self.logs_dir))}",
            '',
            '# Helper functions for I/O paths',
            'def get_output_path(filename):',
            '    """Get the full path for an output file. ALL outputs should use this."""',
            "    return os.path.join(os.environ['SKILL_OUTPUT_DIR'], filename)",
            '',
            f'SKILL_OUTPUT_DIR = {repr(str(self.output_dir))}',
            f'SKILL_LOGS_DIR = {repr(str(self.logs_dir))}',
        ]

        # Add working directory to sys.path for imports and change to it
        if input_spec.working_dir:
            work_dir = str(input_spec.working_dir)
            lines.extend([
                '',
                '# Setup working directory for resource access (READ-ONLY for resources)',
                f'_skill_dir = {repr(work_dir)}',
                "os.environ['SKILL_DIR'] = _skill_dir",
                'SKILL_DIR = _skill_dir',
                'if _skill_dir not in sys.path:',
                '    sys.path.insert(0, _skill_dir)',
                'os.chdir(_skill_dir)',
            ])

        # Add custom env vars
        for key, value in input_spec.env_vars.items():
            lines.append(f'os.environ[{repr(key)}] = {repr(value)}')

        # Add args
        if input_spec.args:
            lines.append('')
            lines.append('# Command line arguments')
            args_str = repr(input_spec.args)
            lines.append(f'ARGS = {args_str}')
            lines.append('sys.argv = ["script.py"] + [str(a) for a in ARGS]')

        lines.append('')
        return '\n'.join(lines)

    def _generate_local_js_env_setup(self, input_spec: ExecutionInput) -> str:
        """Generate JavaScript code to setup environment for local execution."""
        lines = [
            '// Environment setup for local execution',
            f'process.env.SKILL_OUTPUT_DIR = {repr(str(self.output_dir))};',
            f'process.env.SKILL_LOGS_DIR = {repr(str(self.logs_dir))};',
        ]

        for key, value in input_spec.env_vars.items():
            lines.append(f'process.env.{key} = {repr(value)};')

        lines.append('')
        return '\n'.join(lines)

    def _parse_sandbox_result(self,
                              results: Dict[str, Any]) -> tuple[str, str, int]:
        """Parse sandbox execution results into stdout, stderr, exit_code."""
        stdout_parts = []
        stderr_parts = []
        exit_code = 0

        for executor_type in ['python_executor', 'shell_executor']:
            if executor_type in results:
                for result in results[executor_type]:
                    if result.get('output'):
                        stdout_parts.append(result['output'])
                    if result.get('error'):
                        stderr_parts.append(result['error'])
                    if result.get('status', 0) != 0:
                        exit_code = result.get('status', -1)

        return '\n'.join(stdout_parts), '\n'.join(stderr_parts), exit_code

    async def _execute_in_sandbox(
            self,
            python_code: Union[str, List[str]] = None,
            shell_command: Union[str, List[str]] = None,
            requirements: List[str] = None) -> Dict[str, Any]:
        """Execute code in EnclaveSandbox."""
        sandbox = self._get_sandbox()
        return await sandbox.async_execute(
            python_code=python_code,
            shell_command=shell_command,
            requirements=requirements)

    async def execute_python_script(
            self,
            script_path: Union[str, Path],
            skill_id: str = 'unknown',
            input_spec: ExecutionInput = None) -> ExecutionOutput:
        """
        Execute a Python script file.

        Uses sandbox mode or local mode based on use_sandbox setting.

        Args:
            script_path: Path to the Python script.
            skill_id: Identifier of the skill being executed.
            input_spec: Input specification.

        Returns:
            ExecutionOutput with results.
        """
        input_spec = input_spec or ExecutionInput()
        script_path = Path(script_path)

        record = self._create_record(
            skill_id=skill_id,
            executor_type=ExecutorType.PYTHON_SCRIPT,
            input_spec=input_spec,
            script_path=str(script_path))

        record.start_time = datetime.now()
        record.status = ExecutionStatus.RUNNING

        try:
            # Read script content
            with open(script_path, 'r', encoding='utf-8') as f:
                code = f.read()

            # Security check (stricter for local mode)
            is_safe, reason = self._security_check(
                code, is_local=not self.use_sandbox)
            if not is_safe:
                record.status = ExecutionStatus.SECURITY_BLOCKED
                record.error_message = reason
                output = ExecutionOutput(
                    stderr=f'Security check failed: {reason}', exit_code=-1)
                record.end_time = datetime.now()
                record.output_spec = output
                self.spec.add_record(record)
                return output

            start_time = datetime.now()

            if self.use_sandbox:
                # Sandbox mode: inject environment and execute
                env_setup = self._generate_env_setup(input_spec, {})
                full_code = env_setup + '\n' + code

                results = await self._execute_in_sandbox(
                    python_code=full_code,
                    requirements=input_spec.requirements)
                stdout, stderr, exit_code = self._parse_sandbox_result(results)
            else:
                # Local mode: execute directly
                stdout, stderr, exit_code = await self._local_execute_python_code(
                    code, input_spec)

            end_time = datetime.now()

            output = ExecutionOutput(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                output_files=self._collect_output_files(),
                duration_ms=(end_time - start_time).total_seconds() * 1000)

            record.status = (
                ExecutionStatus.SUCCESS
                if exit_code == 0 else ExecutionStatus.FAILED)

        except Exception as e:
            output = ExecutionOutput(stderr=str(e), exit_code=-1)
            record.status = ExecutionStatus.FAILED
            record.error_message = str(e)
            logger.error(f'Python script execution failed: {e}')

        record.end_time = datetime.now()
        record.output_spec = output
        self.spec.add_record(record)
        return output

    async def execute_python_code(
            self,
            code: str,
            skill_id: str = 'unknown',
            input_spec: ExecutionInput = None) -> ExecutionOutput:
        """
        Execute Python code string.

        Uses sandbox mode or local mode based on use_sandbox setting.

        Args:
            code: Python code to execute.
            skill_id: Identifier of the skill being executed.
            input_spec: Input specification.

        Returns:
            ExecutionOutput with results.
        """
        input_spec = input_spec or ExecutionInput()

        record = self._create_record(
            skill_id=skill_id,
            executor_type=ExecutorType.PYTHON_CODE,
            input_spec=input_spec,
            script_path='<inline>')

        record.start_time = datetime.now()
        record.status = ExecutionStatus.RUNNING

        try:
            # Security check (stricter for local mode)
            is_safe, reason = self._security_check(
                code, is_local=not self.use_sandbox)
            if not is_safe:
                record.status = ExecutionStatus.SECURITY_BLOCKED
                record.error_message = reason
                output = ExecutionOutput(
                    stderr=f'Security check failed: {reason}', exit_code=-1)
                record.end_time = datetime.now()
                record.output_spec = output
                self.spec.add_record(record)
                return output

            start_time = datetime.now()

            if self.use_sandbox:
                # Sandbox mode
                env_setup = self._generate_env_setup(input_spec, {})
                full_code = env_setup + '\n' + code

                results = await self._execute_in_sandbox(
                    python_code=full_code,
                    requirements=input_spec.requirements)
                stdout, stderr, exit_code = self._parse_sandbox_result(results)
            else:
                # Local mode
                stdout, stderr, exit_code = await self._local_execute_python_code(
                    code, input_spec)

            end_time = datetime.now()

            output = ExecutionOutput(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                output_files=self._collect_output_files(),
                duration_ms=(end_time - start_time).total_seconds() * 1000)

            record.status = (
                ExecutionStatus.SUCCESS
                if exit_code == 0 else ExecutionStatus.FAILED)

        except Exception as e:
            output = ExecutionOutput(stderr=str(e), exit_code=-1)
            record.status = ExecutionStatus.FAILED
            record.error_message = str(e)
            logger.error(f'Python code execution failed: {e}')

        record.end_time = datetime.now()
        record.output_spec = output
        self.spec.add_record(record)
        return output

    def _generate_env_setup(self, input_spec: ExecutionInput,
                            sandbox_files: Dict[str, str]) -> str:
        """Generate Python code to setup environment variables and paths."""
        sandbox_logs_dir = f'{self.SANDBOX_ROOT}/logs'
        lines = [
            'import os',
            'import sys',
            '',
            '# Setup environment',
            f"os.environ['SKILL_OUTPUT_DIR'] = '{self.SANDBOX_OUTPUT_DIR}'",
            f"os.environ['SKILL_LOGS_DIR'] = '{sandbox_logs_dir}'",
            '',
            '# Helper functions for I/O paths',
            'def get_output_path(filename):',
            '    """Get the full path for an output file. ALL outputs should use this."""',
            "    return os.path.join(os.environ['SKILL_OUTPUT_DIR'], filename)",
            '',
            f"SKILL_OUTPUT_DIR = '{self.SANDBOX_OUTPUT_DIR}'",
            f"SKILL_LOGS_DIR = '{sandbox_logs_dir}'",
        ]

        # Add custom env vars
        for key, value in input_spec.env_vars.items():
            # Sanitize value to prevent injection
            safe_value = value.replace("'", "\\'")
            lines.append(f"os.environ['{key}'] = '{safe_value}'")

        # Add args
        if input_spec.args:
            lines.append('')
            lines.append('# Command line arguments')
            args_str = repr(input_spec.args)
            lines.append(f'ARGS = {args_str}')
            lines.append('sys.argv = ["script.py"] + [str(a) for a in ARGS]')

        lines.append('')
        return '\n'.join(lines)

    def execute_python_function(
            self,
            func: Callable,
            skill_id: str = 'unknown',
            input_spec: ExecutionInput = None) -> ExecutionOutput:
        """
        Execute a Python function directly (local execution, not sandboxed).

        Note: Function execution runs locally as it cannot be serialized to sandbox.
        Use execute_python_code for sandboxed execution.

        Args:
            func: Python callable to execute.
            skill_id: Identifier of the skill being executed.
            input_spec: Input specification with args and kwargs.

        Returns:
            ExecutionOutput with results.
        """
        input_spec = input_spec or ExecutionInput()

        record = self._create_record(
            skill_id=skill_id,
            executor_type=ExecutorType.PYTHON_FUNCTION,
            input_spec=input_spec,
            function_name=func.__name__)
        record.sandbox_used = False  # Local execution

        record.start_time = datetime.now()
        record.status = ExecutionStatus.RUNNING

        try:
            # Add helper paths to kwargs
            kwargs = input_spec.kwargs.copy()
            kwargs['_output_dir'] = self.output_dir

            start_time = datetime.now()
            return_value = func(*input_spec.args, **kwargs)
            end_time = datetime.now()

            output = ExecutionOutput(
                return_value=return_value,
                exit_code=0,
                output_files=self._collect_output_files(),
                duration_ms=(end_time - start_time).total_seconds() * 1000)

            record.status = ExecutionStatus.SUCCESS

        except Exception as e:
            output = ExecutionOutput(stderr=str(e), exit_code=-1)
            record.status = ExecutionStatus.FAILED
            record.error_message = str(e)
            logger.error(f'Python function execution failed: {e}')

        record.end_time = datetime.now()
        record.output_spec = output
        self.spec.add_record(record)
        return output

    async def execute_shell(
            self,
            command: Union[str, List[str]],
            skill_id: str = 'unknown',
            input_spec: ExecutionInput = None) -> ExecutionOutput:
        """
        Execute a shell command.

        Uses sandbox mode or local mode based on use_sandbox setting.

        Args:
            command: Shell command string or list of commands.
            skill_id: Identifier of the skill being executed.
            input_spec: Input specification.

        Returns:
            ExecutionOutput with results.
        """
        input_spec = input_spec or ExecutionInput()

        cmd_str = command if isinstance(command, str) else ' && '.join(command)

        record = self._create_record(
            skill_id=skill_id,
            executor_type=ExecutorType.SHELL,
            input_spec=input_spec,
            script_path=cmd_str[:200])

        record.start_time = datetime.now()
        record.status = ExecutionStatus.RUNNING

        try:
            # Security check (stricter for local mode)
            is_safe, reason = self._security_check(
                cmd_str, is_local=not self.use_sandbox)
            if not is_safe:
                record.status = ExecutionStatus.SECURITY_BLOCKED
                record.error_message = reason
                output = ExecutionOutput(
                    stderr=f'Security check failed: {reason}', exit_code=-1)
                record.end_time = datetime.now()
                record.output_spec = output
                self.spec.add_record(record)
                return output

            start_time = datetime.now()

            if self.use_sandbox:
                # Sandbox mode: prepend environment setup
                env_exports = [
                    f"export SKILL_OUTPUT_DIR='{self.SANDBOX_OUTPUT_DIR}'",
                ]
                for key, value in input_spec.env_vars.items():
                    safe_value = value.replace("'", "\\'")
                    env_exports.append(f"export {key}='{safe_value}'")

                full_cmd = ' && '.join(env_exports + [cmd_str])

                results = await self._execute_in_sandbox(shell_command=full_cmd
                                                         )
                stdout, stderr, exit_code = self._parse_sandbox_result(results)
            else:
                # Local mode
                stdout, stderr, exit_code = await self._local_execute_shell(
                    cmd_str, input_spec)

            end_time = datetime.now()

            output = ExecutionOutput(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                output_files=self._collect_output_files(),
                duration_ms=(end_time - start_time).total_seconds() * 1000)

            record.status = (
                ExecutionStatus.SUCCESS
                if exit_code == 0 else ExecutionStatus.FAILED)

        except Exception as e:
            output = ExecutionOutput(stderr=str(e), exit_code=-1)
            record.status = ExecutionStatus.FAILED
            record.error_message = str(e)
            logger.error(f'Shell execution failed: {e}')

        record.end_time = datetime.now()
        record.output_spec = output
        self.spec.add_record(record)
        return output

    async def execute_javascript(self,
                                 script_path: Union[str, Path] = None,
                                 code: str = None,
                                 skill_id: str = 'unknown',
                                 input_spec: ExecutionInput = None,
                                 runtime: str = 'node') -> ExecutionOutput:
        """
        Execute JavaScript code via Node.js.

        Uses sandbox mode or local mode based on use_sandbox setting.

        Args:
            script_path: Path to JavaScript file.
            code: Inline JavaScript code (if no script_path).
            skill_id: Identifier of the skill being executed.
            input_spec: Input specification.
            runtime: JavaScript runtime ('node' or 'deno').

        Returns:
            ExecutionOutput with results.
        """
        input_spec = input_spec or ExecutionInput()

        record = self._create_record(
            skill_id=skill_id,
            executor_type=ExecutorType.JAVASCRIPT,
            input_spec=input_spec,
            script_path=str(script_path) if script_path else '<inline>')

        record.start_time = datetime.now()
        record.status = ExecutionStatus.RUNNING

        try:
            # Get JavaScript code
            if script_path:
                with open(script_path, 'r', encoding='utf-8') as f:
                    js_code = f.read()
            elif code:
                js_code = code
            else:
                raise ValueError('Either script_path or code must be provided')

            # Security check (stricter for local mode)
            is_safe, reason = self._security_check(
                js_code, is_local=not self.use_sandbox)
            if not is_safe:
                record.status = ExecutionStatus.SECURITY_BLOCKED
                record.error_message = reason
                output = ExecutionOutput(
                    stderr=f'Security check failed: {reason}', exit_code=-1)
                record.end_time = datetime.now()
                record.output_spec = output
                self.spec.add_record(record)
                return output

            start_time = datetime.now()

            if self.use_sandbox:
                # Sandbox mode: write JS file and execute
                js_filename = f'script_{uuid.uuid4().hex[:8]}.js'
                js_path = self.scripts_dir / js_filename
                sandbox_js_path = f'{self.SANDBOX_WORK_DIR}/{js_filename}'

                # Inject environment into JS code
                env_inject = self._generate_js_env_setup(input_spec, {})
                full_js_code = env_inject + '\n' + js_code

                with open(js_path, 'w', encoding='utf-8') as f:
                    f.write(full_js_code)

                # Build shell command to run JS
                args_str = ' '.join(f'"{arg}"' for arg in input_spec.args)
                shell_cmd = f'{runtime} {sandbox_js_path} {args_str}'

                results = await self._execute_in_sandbox(
                    shell_command=shell_cmd)
                stdout, stderr, exit_code = self._parse_sandbox_result(results)
            else:
                # Local mode
                stdout, stderr, exit_code = await self._local_execute_javascript(
                    js_code, input_spec)

            end_time = datetime.now()

            output = ExecutionOutput(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                output_files=self._collect_output_files(),
                duration_ms=(end_time - start_time).total_seconds() * 1000)

            record.status = (
                ExecutionStatus.SUCCESS
                if exit_code == 0 else ExecutionStatus.FAILED)

        except Exception as e:
            output = ExecutionOutput(stderr=str(e), exit_code=-1)
            record.status = ExecutionStatus.FAILED
            record.error_message = str(e)
            logger.error(f'JavaScript execution failed: {e}')

        record.end_time = datetime.now()
        record.output_spec = output
        self.spec.add_record(record)
        return output

    def _generate_js_env_setup(self, input_spec: ExecutionInput,
                               sandbox_files: Dict[str, str]) -> str:
        """Generate JavaScript code to setup environment."""
        lines = [
            '// Environment setup',
            f"process.env.SKILL_OUTPUT_DIR = '{self.SANDBOX_OUTPUT_DIR}';",
        ]

        for key, value in input_spec.env_vars.items():
            safe_value = value.replace("'", "\\'")
            lines.append(f"process.env.{key} = '{safe_value}';")

        lines.append('')
        return '\n'.join(lines)

    async def execute(self,
                      executor_type: ExecutorType,
                      skill_id: str = 'unknown',
                      script_path: Union[str, Path] = None,
                      func: Callable = None,
                      command: Union[str, List[str]] = None,
                      code: str = None,
                      input_spec: ExecutionInput = None,
                      **kwargs) -> ExecutionOutput:
        """
        Unified async execution interface.

        Args:
            executor_type: Type of executor to use.
            skill_id: Identifier of the skill.
            script_path: Path to script file (for PYTHON_SCRIPT, JAVASCRIPT).
            func: Callable function (for PYTHON_FUNCTION).
            command: Shell command (for SHELL).
            code: Inline code (for PYTHON_CODE, JAVASCRIPT).
            input_spec: Input specification.
            **kwargs: Additional executor-specific arguments.

        Returns:
            ExecutionOutput with results.
        """
        if executor_type == ExecutorType.PYTHON_SCRIPT:
            return await self.execute_python_script(
                script_path=script_path,
                skill_id=skill_id,
                input_spec=input_spec)
        elif executor_type == ExecutorType.PYTHON_CODE:
            return await self.execute_python_code(
                code=code, skill_id=skill_id, input_spec=input_spec)
        elif executor_type == ExecutorType.PYTHON_FUNCTION:
            return self.execute_python_function(
                func=func, skill_id=skill_id, input_spec=input_spec)
        elif executor_type == ExecutorType.SHELL:
            return await self.execute_shell(
                command=command, skill_id=skill_id, input_spec=input_spec)
        elif executor_type == ExecutorType.JAVASCRIPT:
            return await self.execute_javascript(
                script_path=script_path,
                code=code,
                skill_id=skill_id,
                input_spec=input_spec,
                **kwargs)
        else:
            raise ValueError(f'Unsupported executor type: {executor_type}')

    def execute_sync(self,
                     executor_type: ExecutorType,
                     skill_id: str = 'unknown',
                     **kwargs) -> ExecutionOutput:
        """Synchronous wrapper for execute()."""
        return asyncio.run(self.execute(executor_type, skill_id, **kwargs))

    def link_skills(self,
                    upstream_skill_id: str,
                    downstream_input_key: str,
                    output_key: str = None) -> Optional[Any]:
        """
        Link output from upstream skill to downstream skill input.

        Args:
            upstream_skill_id: ID of the upstream skill.
            downstream_input_key: Key to use in downstream input.
            output_key: Specific output key to link (e.g., 'return_value', 'stdout').

        Returns:
            The linked value, or None if not found.
        """
        if upstream_skill_id in self.spec.upstream_outputs:
            output = self.spec.upstream_outputs[upstream_skill_id]
            if output_key:
                return getattr(output, output_key, None)
            return output.return_value or output.stdout
        return None

    def get_spec_log(self) -> str:
        """Get the execution spec as markdown string."""
        return self.spec.to_markdown()

    def save_spec_log(self, output_path: Union[str, Path] = None):
        """Save the execution spec to a markdown file in logs directory."""
        if output_path is None:
            output_path = self.logs_dir / 'execution_spec.md'
        self.spec.save(output_path)
        logger.info(f'Saved execution spec to: {output_path}')

    def cleanup(self, keep_spec: bool = True):
        """
        Clean up workspace directory.

        Args:
            keep_spec: If True, saves spec before cleanup.
        """
        if keep_spec:
            self.save_spec_log()
        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir)
            logger.info(f'Cleaned up workspace: {self.workspace_dir}')
