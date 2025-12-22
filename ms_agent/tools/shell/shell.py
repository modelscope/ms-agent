import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR


class Shell(ToolBase):

    def __init__(self, config):
        super().__init__(config)
        self.output_dir = getattr(self.config, 'output_dir',
                                  DEFAULT_OUTPUT_DIR)

    async def connect(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools = {
            'shell': [
                Tool(
                    tool_name='execute_single',
                    server_name='shell',
                    description='Execute a single shell command. '
                    'Use this tool to read/write/create file/dirs, '
                    'or start/stop processes or install required packages.'
                    'Note:\n '
                    '1. Do not execute dangerous commands which will affect the file system '
                    'or other processes\n '
                    '2. The work_dir arg should always base on the project you are working on',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'command': {
                                'type': 'string',
                                'description': 'The shell command to execute.',
                            },
                            'work_dir': {
                                'type':
                                'string',
                                'description':
                                'The work dir of the command, this argument should always '
                                'be a relative sub folder of the project you are working on.',
                            }
                        },
                        'required': ['command', 'work_dir'],
                        'additionalProperties': False
                    }),
            ]
        }
        return tools

    def check_safe(self, command, work_dir):
        # 1. Check work_dir
        output_dir_abs = Path(self.output_dir).resolve()
        if work_dir.startswith('/') or work_dir.startswith('~'):
            work_dir_abs = Path(work_dir).resolve()
        else:
            work_dir_abs = (output_dir_abs / work_dir).resolve()

        if not str(work_dir_abs).startswith(str(output_dir_abs)):
            raise ValueError(
                f"Work directory '{work_dir}' is outside allowed directory '{self.output_dir}'"
            )

        # 2. Check dangerous commands
        dangerous_commands = [
            r'\brm\s+-rf\s+/',  # rm -rf /
            r'\bsudo\b',  # sudo
            r'\bsu\b',  # su
            r'\bchmod\b',  # chmod
            r'\bchown\b',  # chown
            r'\breboot\b',  # reboot
            r'\bshutdown\b',  # shutdown
            r'\bmkfs\b',  # mkfs
            r'\bdd\b',  # dd
            r'\bcurl\b.*\|\s*bash',  # curl | bash
            r'\bwget\b.*\|\s*bash',  # wget | bash
            r'\bcurl\b.*\|\s*sh\b',  # curl | sh
            r'\bwget\b.*\|\s*sh\b',  # wget | sh
            r'\b:\(\)\{.*\|.*&\s*\}',  # fork bomb
            r'\bmount\b',  # mount
            r'\bumount\b',  # umount
            r'\bfdisk\b',  # fdisk
            r'\bparted\b',  # parted
        ]

        for pattern in dangerous_commands:
            if re.search(pattern, command, re.IGNORECASE):
                raise ValueError(
                    f'Command contains dangerous operation: {pattern}')

        # 3. Check path traversal
        suspicious_patterns = [
            r'(?:^|\s)/',  # absolute path
            r'\.\.',  # parent directory
            r'~',  # HOME
            r'\$HOME',  # HOME env
            r'\$\{HOME\}',  # ${HOME}
        ]

        for pattern in suspicious_patterns:
            if re.search(pattern, command):
                # 提取所有可能的路径
                potential_paths = re.findall(r'(?:^|\s)([\w\./~${}]+)',
                                             command)
                for path_str in potential_paths:
                    if not path_str:
                        continue

                    try:
                        expanded_path = os.path.expandvars(
                            os.path.expanduser(path_str))
                        if not os.path.isabs(expanded_path):
                            full_path = (work_dir_abs
                                         / expanded_path).resolve()
                        else:
                            full_path = Path(expanded_path).resolve()
                        if not str(full_path).startswith(str(output_dir_abs)):
                            raise ValueError(
                                f"Command attempts to access path outside allowed directory: '{path_str}' "
                                f"resolves to '{full_path}', which is outside '{self.output_dir}'"
                            )
                    except Exception:  # noqa
                        continue

        # 4. Check dangerous redirections
        redirect_patterns = [
            r'>+\s*/(?!tmp/|var/tmp/|dev/null)',  # redirect to root directory (except /tmp/, /var/tmp/, /dev/null)
            r'<\s*/etc/',  # read from /etc
            r'>+\s*/dev/(?!null)',  # redirect to device files (except /dev/null)
        ]

        for pattern in redirect_patterns:
            if re.search(pattern, command):
                raise ValueError('Command contains dangerous redirection')

        # 5. Check environment variable modifications
        if re.search(r'\bexport\b|\benv\b.*=', command, re.IGNORECASE):
            if re.search(r'\bPATH\s*=|LD_PRELOAD|LD_LIBRARY_PATH', command,
                         re.IGNORECASE):
                raise ValueError(
                    'Command attempts to modify critical (PATH/LD_PRELOAD/LD_LIBRARY_PATH) '
                    'environment variables')

        # 6. Check for command substitution and other shell injection risks
        shell_injection_patterns = [
            r'\$\(.*\)',  # command substitution $(...)
            r'`.*`',  # command substitution `...`
        ]

        for pattern in shell_injection_patterns:
            if re.search(pattern, command):
                substituted = re.findall(pattern, command)
                for sub_cmd in substituted:
                    inner_cmd = re.sub(r'[\$\(\)`]', '', sub_cmd)
                    for dangerous in dangerous_commands:
                        if re.search(dangerous, inner_cmd, re.IGNORECASE):
                            raise ValueError(
                                f'Command substitution contains dangerous operation: {inner_cmd}'
                            )

    async def execute_shell(self, command: str, work_dir: str):
        try:
            self.check_safe(command, work_dir)
            if work_dir == '.' or work_dir == '.' + os.sep:
                work_dir = ''
            work_dir = os.path.join(self.output_dir, work_dir)
            Path(work_dir).mkdir(parents=True, exist_ok=True)
            ret = subprocess.run(
                command,
                shell=True,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=getattr(self.config.tools.shell, 'timeout', 5),
            )

            if ret.returncode == 0:
                result = f'Command executed successfully. return_code=0, output: {ret.stdout.strip()}'
            else:
                result = f'Command executed failed. return_code={ret.returncode}, error message: {ret.stderr.strip()}'

        except subprocess.TimeoutExpired:
            result = f'Run timed out after {getattr(self.config.tools.shell, "timeout", 5)} seconds.'
        except Exception as e:
            result = f'Run failed with an exception: {e}.'

        output = (
            f'Shell command status:\n'
            f'Command line: {command}\n'
            f'Workdir: {work_dir}\n'
            f'Result: {result or "The command does not give any responses."}')
        return output

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        if tool_name == 'execute_single':
            return await self.execute_shell(tool_args['command'],
                                            tool_args['work_dir'])
        else:
            return f'Unknown tool type: {tool_name}'
