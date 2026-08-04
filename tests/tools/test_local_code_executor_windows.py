import os
from unittest import mock

from ms_agent.tools.code.local_code_executor import LocalCodeExecutionTool


def _bare_tool() -> LocalCodeExecutionTool:
    """Build a unit-test instance without starting kernels or checking deps."""
    tool = LocalCodeExecutionTool.__new__(LocalCodeExecutionTool)
    tool.tool_config = None
    return tool


def test_composite_command_uses_native_windows_shell():
    command = 'cd work && echo ok > result.txt'
    with mock.patch('ms_agent.tools.code.local_code_executor.os.name', 'nt'):
        assert _bare_tool()._prepare_shell_command(command) == command


def test_sanitized_env_keeps_windows_runtime_variables():
    windows_env = {
        'PATH': r'C:\Windows\System32',
        'SYSTEMROOT': r'C:\Windows',
        'WINDIR': r'C:\Windows',
        'COMSPEC': r'C:\Windows\System32\cmd.exe',
        'PATHEXT': '.COM;.EXE;.BAT;.CMD',
        'TEMP': r'C:\Users\tester\AppData\Local\Temp',
        'TMP': r'C:\Users\tester\AppData\Local\Temp',
        'USERPROFILE': r'C:\Users\tester',
        'HOMEDRIVE': 'C:',
        'HOMEPATH': r'\Users\tester',
        'USERNAME': 'tester',
        'APPDATA': r'C:\Users\tester\AppData\Roaming',
        'LOCALAPPDATA': r'C:\Users\tester\AppData\Local',
        'SECRET_TOKEN': 'must-not-leak',
    }
    with mock.patch.dict(os.environ, windows_env, clear=True), mock.patch(
            'ms_agent.tools.code.local_code_executor.os.name', 'nt'):
        env = _bare_tool()._build_env('shell_env', inherit=False)

    for key in (
            'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
            'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'USERNAME', 'APPDATA',
            'LOCALAPPDATA'):
        assert env[key] == windows_env[key]
    assert env['INHERITED_FROM_LOCAL'] == 'False'
    assert 'SECRET_TOKEN' not in env
