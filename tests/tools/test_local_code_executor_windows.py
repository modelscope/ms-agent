import asyncio
import os
from unittest import mock

from ms_agent.tools.code.local_code_executor import LocalCodeExecutionTool


def _bare_tool() -> LocalCodeExecutionTool:
    """Build a unit-test instance without starting kernels or checking deps."""
    tool = LocalCodeExecutionTool.__new__(LocalCodeExecutionTool)
    tool.tool_config = None
    return tool


class _FakeProcess:

    def __init__(self):
        self.returncode = 0

    async def communicate(self):
        return b'', b''


def _run_shell(command: str):
    """Run one command with the subprocess stubbed, returning what the shell
    would have been handed."""
    tool = _bare_tool()
    tool._shell_timeout = 30
    tool._task_manager = None
    tool.shell_env = {'PATH': '/usr/bin'}
    tool._ws = mock.Mock(root='/tmp')
    tool._artifacts = mock.Mock()
    tool._artifacts.pack_json_shell_result.side_effect = (
        lambda **kwargs: kwargs)
    seen = {}

    async def _fake_exec(cmd, **kwargs):
        seen['cmd'] = cmd
        return _FakeProcess()

    with mock.patch(
            'ms_agent.tools.code.local_code_executor.asyncio.'
            'create_subprocess_shell',
            new=_fake_exec):
        asyncio.run(tool.shell_executor(command=command))
    return seen['cmd']


def test_command_reaches_the_shell_verbatim():
    """No rewriting, whatever punctuation the command contains. Rewriting used
    to switch to a LOGIN shell on metacharacters, so `cmd` and `cmd ; true`
    ran under different PATHs and could resolve different binaries."""
    for command in (
            'python3 -V',
            'python3 -V ; true',
            'pip install jsonschema && python3 -c "import jsonschema"',
            'grep -r x . 2>/dev/null | head -3',
    ):
        assert _run_shell(command) == command


def test_composite_command_uses_native_windows_shell():
    command = 'cd work && echo ok > result.txt'
    with mock.patch('ms_agent.tools.code.local_code_executor.os.name', 'nt'):
        assert _run_shell(command) == command


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


def test_posix_env_carries_identity_tmpdir_tls_and_proxy():
    """Each of these being absent breaks a specific, observed thing — see
    ``_POSIX_ENV_PASSTHROUGH``."""
    parent = {
        'PATH': '/usr/bin',
        'HOME': '/home/tester',
        'USER': 'tester',
        'LOGNAME': 'tester',
        'TMPDIR': '/var/folders/xy/T/',
        'SSL_CERT_FILE': '/etc/ssl/cert.pem',
        'HTTPS_PROXY': 'http://127.0.0.1:7890',
        'TERM': 'xterm-256color',
        'AWS_SECRET_ACCESS_KEY': 'must-not-leak',
        'OPENAI_API_KEY': 'must-not-leak',
    }
    with mock.patch.dict(os.environ, parent, clear=True), mock.patch(
            'ms_agent.tools.code.local_code_executor.os.name', 'posix'):
        env = _bare_tool()._build_env('shell_env', inherit=False)

    for key in ('PATH', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'SSL_CERT_FILE',
                'HTTPS_PROXY', 'TERM'):
        assert env[key] == parent[key], key
    assert 'AWS_SECRET_ACCESS_KEY' not in env
    assert 'OPENAI_API_KEY' not in env

    # And a parent without a variable must not have one invented for it:
    # passing an empty TMPDIR is worse than passing none.
    with mock.patch.dict(os.environ, {'PATH': '/usr/bin'}, clear=True), \
            mock.patch('ms_agent.tools.code.local_code_executor.os.name',
                       'posix'):
        sparse = _bare_tool()._build_env('shell_env', inherit=False)
    assert 'TMPDIR' not in sparse
    assert 'USER' not in sparse


def test_agent_env_overrides_the_parents_interactive_settings():
    """Set outright, not inherited: these exist to undo settings made for a
    human at a terminal. A developer's `PAGER=less` is precisely the value
    that leaves `git log` waiting for a keypress — observed live."""
    from ms_agent.tools.code.local_code_executor import _AGENT_FRIENDLY_ENV

    hostile_parent = {
        'PATH': '/usr/bin',
        'PAGER': 'less',
        'GIT_PAGER': 'less',
        'LESS': '-R',
        'AI_AGENT': 'some-other-agent',
        'NO_COLOR': '',
        'GIT_TERMINAL_PROMPT': '1',
    }
    with mock.patch.dict(os.environ, hostile_parent, clear=True), mock.patch(
            'ms_agent.tools.code.local_code_executor.os.name', 'posix'):
        env = _bare_tool()._build_env('shell_env', inherit=False)

    for key, expected in _AGENT_FRIENDLY_ENV.items():
        assert env[key] == expected, f'{key} inherited from the parent'
    assert env['PAGER'] == 'cat'
    assert env['AI_AGENT'] == 'ms_agent'
    assert env['GIT_TERMINAL_PROMPT'] == '0'


def test_config_can_still_override_the_agent_defaults():
    """Forcing them must not take away the deliberate-choice channel."""
    from types import SimpleNamespace

    tool = _bare_tool()
    tool.tool_config = SimpleNamespace(shell_env={'PAGER': 'bat'})
    with mock.patch.dict(os.environ, {'PATH': '/usr/bin'}, clear=True), \
            mock.patch('ms_agent.tools.code.local_code_executor.os.name',
                       'posix'):
        env = tool._build_env('shell_env', inherit=False)
    assert env['PAGER'] == 'bat'
    assert env['GIT_PAGER'] == 'cat'  # untouched keys keep the safe default
